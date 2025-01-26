import sys
import re
import csv
import os
import logging
import requests  # Added import for fetching thumbnails

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QProgressBar,
    QMenuBar,
    QMenu,
    QFileDialog,
    QPlainTextEdit
)
from PyQt6.QtGui import QAction, QIcon, QPixmap
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject

# For Downloading via yt-dlp
try:
    from yt_dlp import YoutubeDL
except ImportError:
    raise ImportError("Please install yt-dlp (pip install yt-dlp).")

# --------------------------------------------------------------------------
# LOG SIGNAL AND CUSTOM LOGGER HANDLER
# --------------------------------------------------------------------------
class LogSignal(QObject):
    """Signal object to emit log messages safely across threads."""
    newLog = pyqtSignal(str)

class QtLogHandler(logging.Handler):
    """
    A logging handler that emits log records via a PyQt signal.
    Allows threads to log messages and have them appear in the GUI.
    """
    def __init__(self, signal_obj: LogSignal):
        super().__init__()
        self.log_signal = signal_obj

    def emit(self, record):
        # Format the log message
        msg = self.format(record)
        # Emit the signal (the main thread will catch it and update the UI)
        self.log_signal.newLog.emit(msg)

# --------------------------------------------------------------------------
# SETUP GLOBAL LOGGER
# --------------------------------------------------------------------------
logger = logging.getLogger("SniperzDownloader")
logger.setLevel(logging.DEBUG)  # Set to DEBUG for detailed logs

# --------------------------------------------------------------------------
# SCRAPE WORKER (YT-DLP)
# --------------------------------------------------------------------------
class ScrapeWorker(QThread):
    """
    Runs the scraping task in a separate thread using yt-dlp.
    Emits signals for progress and individual video results.
    """
    videoScraped = pyqtSignal(dict)          # Emits individual video data
    progressUpdated = pyqtSignal(int, int)   # (current_index, total)
    done = pyqtSignal()                      # Signals when all scraping is done

    def __init__(self, channels, headless=True):
        super().__init__()
        self.channels = channels
        self.headless = headless
        self._is_running = True  # Flag to control thread execution

    def run(self):
        logger.info("Starting scraping with yt-dlp...")

        total_channels = len(self.channels)
        logger.info(f"Total channels to scrape: {total_channels}")

        for idx, channel_url in enumerate(self.channels):
            if not self._is_running:
                logger.info("Scraping canceled by user.")
                break

            self.progressUpdated.emit(idx + 1, total_channels)
            logger.info(f"Scraping channel {idx + 1}/{total_channels}: {channel_url}")

            # Extract video entries using yt-dlp
            try:
                ydl_opts = {
                    'quiet': True,
                    'extract_flat': True,
                    'skip_download': True,
                    'ignoreerrors': True,
                }
                with YoutubeDL(ydl_opts) as ydl:
                    logger.debug(f"Extracting videos from: {channel_url}")
                    info = ydl.extract_info(channel_url, download=False)
            except Exception as e:
                logger.error(f"Error extracting info from {channel_url}: {e}")
                continue  # Proceed to next channel

            if 'entries' not in info:
                logger.error(f"No entries found for channel: {channel_url}")
                continue

            for entry in info['entries']:
                if not self._is_running:
                    logger.info("Scraping canceled by user.")
                    break

                if entry is None:
                    continue  # Skip if entry extraction failed

                video_url = entry.get('url', '')
                title = entry.get('title', 'No Title')

                # Filter for Shorts based on URL containing '/shorts/'
                if '/shorts/' in video_url:
                    video_id = self.get_video_id(video_url)
                    if not video_id:
                        logger.warning(f"Could not extract video ID from URL: {video_url}")
                        continue

                    full_url = f"https://www.youtube.com/watch?v={video_id}"
                    video_data = {
                        'title': title,
                        'url': full_url,
                        'thumbnail_url': self.get_thumbnail_url(full_url)
                    }
                    self.videoScraped.emit(video_data)
                    logger.debug(f"Scraped Shorts video: {title} - {full_url}")

        logger.info("Finished scraping all channels.")
        self.done.emit()

    def get_thumbnail_url(self, video_url):
        """
        Constructs the thumbnail URL based on the video ID extracted from the URL.
        """
        video_id = self.get_video_id(video_url)
        if video_id:
            return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
        return ""

    def get_video_id(self, video_url):
        """
        Extracts the video ID from the full video URL.
        """
        match = re.search(r"v=([^&?/]+)", video_url)
        if match:
            return match.group(1)
        match = re.search(r"/shorts/([^?/]+)", video_url)
        if match:
            return match.group(1)
        return ""

    def stop(self):
        """Stops the thread execution."""
        self._is_running = False

# --------------------------------------------------------------------------
# DOWNLOAD WORKER (YT-DLP)
# --------------------------------------------------------------------------
class DownloadWorker(QThread):
    """
    Downloads each Short video in a separate thread using yt-dlp.
    """
    progressUpdated = pyqtSignal(int, int)  # (current_index, total)
    done = pyqtSignal()                      # Signals when all downloads are done

    def __init__(self, videos_data, download_folder, table_widget):
        """
        videos_data: list of dict { 'title': ..., 'url': ..., 'thumbnail_url': ... }
        download_folder: str (folder path where files should be saved)
        table_widget: QTableWidget instance to update status
        """
        super().__init__()
        self.videos_data = videos_data
        self.download_folder = download_folder
        self.table_widget = table_widget
        self._is_running = True  # Flag to control thread execution

    def run(self):
        total = len(self.videos_data)
        logger.info(f"Starting download of {total} videos to: {self.download_folder}")

        if not os.path.exists(self.download_folder):
            try:
                os.makedirs(self.download_folder)
                logger.debug(f"Created download folder: {self.download_folder}")
            except Exception as e:
                logger.error(f"Could not create folder: {self.download_folder}. Error: {e}")
                self.done.emit()
                return

        # Setup yt-dlp options
        ydl_opts = {
            "format": "mp4/best",
            "outtmpl": os.path.join(self.download_folder, "%(title)s.%(ext)s"),
            "quiet": True,       # We'll handle logging manually
            "no_warnings": True,
            "ignoreerrors": True,  # Continue on download errors
            "retries": 3,          # Retry failed downloads
        }

        with YoutubeDL(ydl_opts) as ydl:
            for i, item in enumerate(self.videos_data):
                if not self._is_running:
                    logger.info("Download canceled by user.")
                    break

                url = item['url']
                row = i
                self.update_status(row, "downloading")
                logger.info(f"Downloading {i + 1}/{total}: {url}")
                try:
                    ydl.download([url])
                    self.update_status(row, "finished")
                    logger.debug(f"Downloaded video: {item['title']}")
                except Exception as e:
                    logger.error(f"Failed to download {url}. Error: {e}")
                    self.update_status(row, "error")

                self.progressUpdated.emit(i + 1, total)

        logger.info("All downloads complete.")
        self.done.emit()

    def update_status(self, row, status):
        emoji = {
            "not_started": "⏳",
            "downloading": "⬇️",
            "finished": "✅",
            "error": "❌",
        }.get(status, "⏳")
        status_item = QTableWidgetItem(emoji)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table_widget.setItem(row, 3, status_item)

    def stop(self):
        """Stops the thread execution."""
        self._is_running = False

# --------------------------------------------------------------------------
# THUMBNAIL LOADER THREAD
# --------------------------------------------------------------------------
class ThumbnailLoader(QThread):
    """
    Loads thumbnail images in a separate thread to prevent blocking the UI.
    """
    thumbnailLoaded = pyqtSignal(int, QPixmap)

    def __init__(self, row, thumb_url):
        super().__init__()
        self.row = row
        self.thumb_url = thumb_url

    def run(self):
        pixmap = None
        try:
            resp = requests.get(self.thumb_url, timeout=10)
            if resp.status_code == 200:
                img_data = resp.content
                pixmap = QPixmap()
                if pixmap.loadFromData(img_data):
                    logger.debug(f"Thumbnail loaded for row {self.row}.")
                else:
                    logger.warning(f"Failed to load pixmap from data: {self.thumb_url}")
        except Exception as e:
            logger.warning(f"Could not load thumbnail: {self.thumb_url}. Error: {e}")

        # Ensure pixmap is always a QPixmap object
        if pixmap is None or pixmap.isNull():
            # Create a default pixmap (e.g., a gray rectangle)
            pixmap = QPixmap(80, 60)
            pixmap.fill(Qt.GlobalColor.gray)
            logger.debug(f"Emitting default pixmap for row {self.row}.")

        self.thumbnailLoaded.emit(self.row, pixmap)
# --------------------------------------------------------------------------
# MAIN WINDOW
# --------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sniperz - YouTube Shorts Bulk Downloader")
        self.setWindowIcon(QIcon("sniperz_icon.png"))  # Ensure 'sniperz_icon.png' is in the script directory

        # Central widget + layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # Menubar
        menubar = QMenuBar()
        file_menu = QMenu("File", self)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        channel_menu = QMenu("Channels", self)
        load_action = QAction("Load from File", self)
        load_action.triggered.connect(self.load_channels_from_file)
        channel_menu.addAction(load_action)

        menubar.addMenu(file_menu)
        menubar.addMenu(channel_menu)
        self.setMenuBar(menubar)

        # Top row: enter channel URLs + scrape + cancel scrape
        top_layout = QHBoxLayout()
        label = QLabel("Enter YouTube Channels Shorts URLs (one per line):")
        self.channel_input = QPlainTextEdit()
        self.channel_input.setPlaceholderText("https://www.youtube.com/@ChannelName/shorts")
        self.channel_input.setFixedHeight(80)  # Increased height

        self.scrape_button = QPushButton("Scrape")
        self.scrape_button.clicked.connect(self.handle_scrape)
        self.scrape_button.setFixedHeight(40)  # Increased height
        self.scrape_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border-radius: 5px;
                font-size: 16px;
                padding: 10px;
            }
            QPushButton:disabled {
                background-color: #A5D6A7;
            }
        """)

        self.cancel_scrape_button = QPushButton("Cancel Scrape")
        self.cancel_scrape_button.clicked.connect(self.cancel_scrape)
        self.cancel_scrape_button.setFixedHeight(40)  # Increased height
        self.cancel_scrape_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border-radius: 5px;
                font-size: 16px;
                padding: 10px;
            }
            QPushButton:disabled {
                background-color: #EF9A9A;
            }
        """)
        self.cancel_scrape_button.setEnabled(False)  # Initially disabled

        # top_layout => label, channel_input, Scrape, Cancel Scrape
        top_layout.addWidget(label)
        top_layout.addWidget(self.channel_input)
        top_layout.addWidget(self.scrape_button)
        top_layout.addWidget(self.cancel_scrape_button)

        # Second row: download folder + browse button
        folder_layout = QHBoxLayout()
        folder_label = QLabel("Download Folder:")
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Choose output folder for downloaded videos")
        self.folder_edit.setFixedHeight(30)  # Increased height
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.browse_folder)
        self.browse_button.setFixedHeight(40)  # Increased height
        self.browse_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border-radius: 5px;
                font-size: 16px;
                padding: 10px;
            }
            QPushButton:disabled {
                background-color: #90CAF9;
            }
        """)

        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_edit)
        folder_layout.addWidget(self.browse_button)

        # Third row: Export CSV, Download Videos, Cancel Download
        action_layout = QHBoxLayout()
        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self.export_csv)
        self.export_button.setEnabled(False)
        self.export_button.setFixedHeight(40)  # Increased height
        self.export_button.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border-radius: 5px;
                font-size: 16px;
                padding: 10px;
            }
            QPushButton:disabled {
                background-color: #FFE0B2;
            }
        """)

        self.download_button = QPushButton("Download Videos")
        self.download_button.clicked.connect(self.handle_download_videos)
        self.download_button.setEnabled(False)
        self.download_button.setFixedHeight(40)  # Increased height
        self.download_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border-radius: 5px;
                font-size: 16px;
                padding: 10px;
            }
            QPushButton:disabled {
                background-color: #EF9A9A;
            }
        """)

        self.cancel_download_button = QPushButton("Cancel Download")
        self.cancel_download_button.clicked.connect(self.cancel_download)
        self.cancel_download_button.setFixedHeight(40)  # Increased height
        self.cancel_download_button.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                border-radius: 5px;
                font-size: 16px;
                padding: 10px;
            }
            QPushButton:disabled {
                background-color: #CE93D8;
            }
        """)
        self.cancel_download_button.setEnabled(False)  # Initially disabled

        action_layout.addWidget(self.export_button)
        action_layout.addWidget(self.download_button)
        action_layout.addWidget(self.cancel_download_button)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(25)  # Slightly increased height

        # Total Videos Label
        self.total_videos_label = QLabel("Total Videos: 0")
        self.total_videos_label.setStyleSheet("font-size: 14px;")
        self.total_videos_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # Table for results
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(["Thumbnail", "Title", "Video URL", "Status"])
        self.results_table.setColumnWidth(0, 100)  # Reduced width for smaller thumbnails
        self.results_table.setColumnWidth(1, 250)  # Adjusted width
        self.results_table.setColumnWidth(2, 250)  # Adjusted width
        self.results_table.setColumnWidth(3, 50)   # Reduced width for status
        self.results_table.verticalHeader().setDefaultSectionSize(60)  # Reduced row height
        self.results_table.setStyleSheet("""
            QTableWidget {
                background-color: #333;
                color: #EEE;
                border: 1px solid #444;
            }
            QHeaderView::section {
                background-color: #555;
                color: white;
                padding: 4px;
                font-size: 14px;
            }
            QTableWidget::item {
                padding: 5px;
            }
        """)

        # Log box
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background-color: #222; color: #DDD; font-family: Consolas;")
        self.log_box.setFixedHeight(150)  # Increased height

        # Assemble main layout
        main_layout.addLayout(top_layout)
        main_layout.addLayout(folder_layout)
        main_layout.addLayout(action_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.total_videos_label)
        main_layout.addWidget(self.results_table)
        main_layout.addWidget(QLabel("Log Output:"))
        main_layout.addWidget(self.log_box)

        # Define status emojis
        self.status_emojis = {
            "not_started": "⏳",
            "downloading": "⬇️",
            "finished": "✅",
            "error": "❌",
        }

        # Setup custom PyQt log handler
        self.log_signal = LogSignal()
        self.log_handler = QtLogHandler(self.log_signal)
        formatter = logging.Formatter(
            fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self.log_handler.setFormatter(formatter)
        logger.addHandler(self.log_handler)
        self.log_signal.newLog.connect(self.append_log)

        # Thread references
        self.scrape_worker = None
        self.download_worker = None
        self.thumbnail_loaders = []  # List to keep track of ThumbnailLoader threads

        # Store scraped data
        self.scraped_data = []
        self.current_row = 0  # To keep track of table rows

        # Load placeholder image
        self.load_placeholder()

    def load_placeholder(self):
        """Load a placeholder image to use when thumbnail fails to load."""
        placeholder_path = "placeholder.png"
        if os.path.exists(placeholder_path):
            self.placeholder_pixmap = QPixmap(placeholder_path).scaled(
                80, 60,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            logger.debug("Loaded placeholder image.")
        else:
            # Create a simple placeholder pixmap if the file doesn't exist
            self.placeholder_pixmap = QPixmap(80, 60)
            self.placeholder_pixmap.fill(Qt.GlobalColor.gray)
            logger.warning("Placeholder image not found. Using a gray rectangle as placeholder.")

    # ---------------------------------------------------------
    # BROWSE FOLDER
    # ---------------------------------------------------------
    def browse_folder(self):
        """Open a dialog to choose the folder for downloads."""
        folder_dialog = QFileDialog(self)
        folder_dialog.setFileMode(QFileDialog.FileMode.Directory)
        folder_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        if folder_dialog.exec():
            path = folder_dialog.selectedFiles()[0]
            self.folder_edit.setText(path)
            logger.info(f"Selected download folder: {path}")

    # ---------------------------------------------------------
    # LOG APPENDING
    # ---------------------------------------------------------
    def append_log(self, msg: str):
        self.log_box.appendPlainText(msg)

    # ---------------------------------------------------------
    # LOAD CHANNELS FROM FILE
    # ---------------------------------------------------------
    def load_channels_from_file(self):
        file_dialog = QFileDialog(self)
        file_path, _ = file_dialog.getOpenFileName(
            self,
            "Open Channel List",
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.read().splitlines()

                # Append loaded channels to the input field
                existing_text = self.channel_input.toPlainText()
                new_text = existing_text + '\n' + '\n'.join([line.strip() for line in lines if line.strip()])
                self.channel_input.setPlainText(new_text)
                logger.info(f"Loaded {len(lines)} channel URLs from file: {file_path}")
            except Exception as e:
                logger.error(f"Error loading channels from file: {e}")

    # ---------------------------------------------------------
    # SCRAPE BUTTON
    # ---------------------------------------------------------
    def handle_scrape(self):
        logger.info("Scrape button clicked. Starting scrape process...")

        # Retrieve channel URLs from input field
        input_text = self.channel_input.toPlainText()
        channels = [line.strip() for line in input_text.splitlines() if line.strip()]

        if not channels:
            logger.warning("No channel URLs provided for scraping.")
            return

        # Validate channel URLs
        valid_channels = []
        invalid_channels = []
        for url in channels:
            if self.validate_channel_url(url):
                valid_channels.append(url)
            else:
                invalid_channels.append(url)

        if invalid_channels:
            logger.warning(f"The following URLs are invalid and will be skipped:\n" + "\n".join(invalid_channels))

        if not valid_channels:
            logger.warning("No valid channel URLs to scrape.")
            return

        logger.info(f"Total valid channels to scrape: {len(valid_channels)}")

        # Disable buttons to prevent multiple operations
        self.scrape_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.cancel_scrape_button.setEnabled(True)  # Enable Cancel Scrape button

        # Change button text to indicate scraping
        self.scrape_button.setText("Scraping...")

        # Clear table & reset
        self.results_table.setRowCount(0)
        self.progress_bar.setValue(0)
        self.total_videos_label.setText("Total Videos: 0")
        self.scraped_data = []
        self.current_row = 0

        logger.info(f"Channels to scrape: {valid_channels}")

        # Initialize ScrapeWorker with headless=True
        self.scrape_worker = ScrapeWorker(valid_channels, headless=True)
        self.scrape_worker.videoScraped.connect(self.add_video_to_table)
        self.scrape_worker.progressUpdated.connect(self.update_progress)
        self.scrape_worker.done.connect(self.scrape_finished)
        self.scrape_worker.start()

    def scrape_finished(self):
        """Handle actions after scraping is complete."""
        logger.info("Scraping completed.")
        self.scrape_button.setEnabled(True)
        self.browse_button.setEnabled(True)
        self.channel_input.setEnabled(True)
        self.scrape_button.setText("Scrape")
        self.cancel_scrape_button.setEnabled(False)  # Disable Cancel Scrape button
        logger.info("Ready for next operation.")

    def validate_channel_url(self, url):
        """
        Validates if the provided URL is a YouTube Shorts channel URL.
        Expected format: https://www.youtube.com/@ChannelName/shorts
        """
        pattern = r"^https?://www\.youtube\.com/@[^/]+/shorts/?$"
        return re.match(pattern, url) is not None

    # ---------------------------------------------------------
    # CANCEL SCRAPE
    # ---------------------------------------------------------
    def cancel_scrape(self):
        """Cancel the ongoing scrape operation."""
        if self.scrape_worker and self.scrape_worker.isRunning():
            logger.info("User requested to cancel scraping.")
            self.scrape_worker.stop()
            self.cancel_scrape_button.setEnabled(False)
            self.scrape_button.setText("Canceling...")
        else:
            logger.warning("No active scrape operation to cancel.")

    # ---------------------------------------------------------
    # ADD VIDEO TO TABLE
    # ---------------------------------------------------------
    def add_video_to_table(self, video_data):
        """Adds a single video entry to the table."""
        row = self.current_row
        self.results_table.insertRow(row)

        title = video_data['title']
        video_url = video_data['url']
        thumb_url = video_data['thumbnail_url']

        # Thumbnail
        thumb_item = QTableWidgetItem()
        thumb_item.setText("")
        thumb_item.setFlags(thumb_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        thumb_item.setData(Qt.ItemDataRole.DecorationRole, self.placeholder_pixmap)  # Set placeholder initially

        # Asynchronously load the thumbnail to avoid blocking the UI
        self.load_thumbnail_async(row, thumb_url)

        # Title
        title_item = QTableWidgetItem(title)
        title_item.setFlags(title_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # Video URL
        url_item = QTableWidgetItem(video_url)
        url_item.setFlags(url_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # Status
        status_item = QTableWidgetItem(self.status_emojis["not_started"])
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        # Add items to table
        self.results_table.setItem(row, 0, thumb_item)
        self.results_table.setItem(row, 1, title_item)
        self.results_table.setItem(row, 2, url_item)
        self.results_table.setItem(row, 3, status_item)

        # Store scraped data
        self.scraped_data.append(video_data)

        self.current_row += 1
        logger.debug(f"Added video to table: {title}")

        # Update total videos count
        self.total_videos_label.setText(f"Total Videos: {len(self.scraped_data)}")

        # Enable download and export buttons if data exists
        if len(self.scraped_data) > 0:
            self.download_button.setEnabled(True)
            self.export_button.setEnabled(True)

    def load_thumbnail_async(self, row, thumb_url):
        """
        Loads thumbnail image asynchronously to prevent UI blocking.
        Updates the table item once the image is loaded.
        """
        thread = ThumbnailLoader(row, thumb_url)
        thread.thumbnailLoaded.connect(self.update_thumbnail)
        thread.finished.connect(lambda: self.remove_thumbnail_loader(thread))
        self.thumbnail_loaders.append(thread)
        thread.start()

    def update_thumbnail(self, row, pixmap):
        """
        Updates the thumbnail in the table once it's loaded.
        """
        if pixmap is not None:
            scaled_pixmap = pixmap.scaled(
                80, 60,  # Smaller thumbnail size
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.results_table.item(row, 0).setData(Qt.ItemDataRole.DecorationRole, scaled_pixmap)
            logger.debug(f"Thumbnail updated for row {row}.")
        else:
            # If pixmap is None, keep the placeholder
            logger.debug(f"Using placeholder for row {row} due to thumbnail load failure.")

    def remove_thumbnail_loader(self, thread):
        """
        Removes the finished ThumbnailLoader thread from the list to prevent memory leaks.
        """
        if thread in self.thumbnail_loaders:
            self.thumbnail_loaders.remove(thread)
            logger.debug(f"ThumbnailLoader thread for row {thread.row} removed.")

    # ---------------------------------------------------------
    # PROGRESS UPDATES (SCRAPE OR DOWNLOAD)
    # ---------------------------------------------------------
    def update_progress(self, current_index, total):
        percent = int((current_index / total) * 100)
        self.progress_bar.setValue(percent)
        logger.debug(f"Progress updated: {current_index}/{total} ({percent}%)")

    # ---------------------------------------------------------
    # EXPORT CSV
    # ---------------------------------------------------------
    def export_csv(self):
        if not self.scraped_data:
            logger.warning("No data to export.")
            return

        file_dialog = QFileDialog(self)
        file_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setNameFilter("CSV Files (*.csv);;All Files (*)")
        if file_dialog.exec():
            csv_path = file_dialog.selectedFiles()[0]
            logger.info(f"Saving CSV to: {csv_path}")
            try:
                with open(csv_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Title", "Video URL", "Thumbnail URL"])
                    for item in self.scraped_data:
                        writer.writerow([
                            item['title'],
                            item['url'],
                            item['thumbnail_url']
                        ])
                logger.info("CSV export complete.")
            except Exception as e:
                logger.error(f"Failed to write CSV: {e}")

    # ---------------------------------------------------------
    # DOWNLOAD VIDEOS (YT-DLP)
    # ---------------------------------------------------------
    def handle_download_videos(self):
        """Download the scraped Shorts to the folder specified in self.folder_edit."""
        if not self.scraped_data:
            logger.warning("No videos to download. Scrape first.")
            return

        download_folder = self.folder_edit.text().strip()
        if not download_folder:
            logger.warning("No download folder selected. Please browse or enter a folder path.")
            return

        logger.info(f"Starting download to folder: {download_folder}")
        self.progress_bar.setValue(0)

        # Disable buttons to prevent multiple operations
        self.download_button.setEnabled(False)
        self.scrape_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.cancel_download_button.setEnabled(True)  # Enable Cancel Download button

        # Change button text to indicate downloading
        self.download_button.setText("Downloading...")

        self.download_worker = DownloadWorker(self.scraped_data, download_folder, self.results_table)
        self.download_worker.progressUpdated.connect(self.update_progress)
        self.download_worker.done.connect(self.download_finished)
        self.download_worker.start()

    def download_finished(self):
        """Handle actions after downloading is complete."""
        logger.info("Downloading completed.")
        self.progress_bar.setValue(100)

        # Re-enable buttons
        self.download_button.setEnabled(True)
        self.scrape_button.setEnabled(True)
        self.export_button.setEnabled(len(self.scraped_data) > 0)
        self.browse_button.setEnabled(True)
        self.cancel_download_button.setEnabled(False)  # Disable Cancel Download button
        self.download_button.setText("Download Videos")
        logger.info("Ready for next operation.")

    # ---------------------------------------------------------
    # CANCEL DOWNLOAD
    # ---------------------------------------------------------
    def cancel_download(self):
        """Cancel the ongoing download operation."""
        if self.download_worker and self.download_worker.isRunning():
            logger.info("User requested to cancel downloading.")
            self.download_worker.stop()
            self.cancel_download_button.setEnabled(False)
            self.download_button.setText("Canceling...")
        else:
            logger.warning("No active download operation to cancel.")

    # ---------------------------------------------------------
    # CLOSE EVENT HANDLER
    # ---------------------------------------------------------
    def closeEvent(self, event):
        """Handle the window close event to ensure all threads are properly terminated."""
        logger.info("Closing application. Waiting for all threads to finish...")

        # Terminate ScrapeWorker if it's running
        if self.scrape_worker and self.scrape_worker.isRunning():
            logger.info("Waiting for ScrapeWorker to finish...")
            self.scrape_worker.stop()
            self.scrape_worker.wait()

        # Terminate DownloadWorker if it's running
        if self.download_worker and self.download_worker.isRunning():
            logger.info("Waiting for DownloadWorker to finish...")
            self.download_worker.stop()
            self.download_worker.wait()

        # Terminate all ThumbnailLoader threads
        for thread in self.thumbnail_loaders:
            if thread.isRunning():
                logger.info(f"Waiting for ThumbnailLoader thread for row {thread.row} to finish...")
                thread.wait()

        logger.info("All threads have been terminated. Application will close now.")
        event.accept()

# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    logger.info("Sniperz - YouTube Shorts Bulk Downloader GUI is now visible. Ready to scrape or download.")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
