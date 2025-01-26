import sys
import re
import csv
import os
import logging

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
# CHANNELS - you can edit or expand this list
# --------------------------------------------------------------------------
ALL_CHANNELS = [
    "https://www.youtube.com/@Allprocessofworld_shorts/shorts",
    "https://www.youtube.com/@TechOnlineShow/shorts",
    "https://www.youtube.com/@Craftsman_Vlog/shorts",
    "https://www.youtube.com/@BestWorkingDay/shorts",
    "https://www.youtube.com/@craftsmanclips/shorts",
    "https://www.youtube.com/@SiragusaMatranga/shorts",
    "https://www.youtube.com/@CraftsmanVision/shorts",
    "https://www.youtube.com/@amazingskills012/shorts",
    "https://www.youtube.com/@Amazing-Making-Process/shorts",
    "https://www.youtube.com/@wisdompouchannel/shorts",
    "https://www.youtube.com/@Deliciousfood-sr1di/shorts",
    "https://www.youtube.com/@theworldspins/shorts",
    "https://www.youtube.com/@CraftsmanWhale/shorts",
    "https://www.youtube.com/@hardworkingday/shorts",
]

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

    def run(self):
        logger.info("Starting scraping with yt-dlp...")

        total_channels = len(self.channels)
        logger.info(f"Total channels to scrape: {total_channels}")

        for idx, channel_url in enumerate(self.channels):
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
                if entry is None:
                    continue  # Skip if entry extraction failed

                video_url = entry.get('url', '')
                title = entry.get('title', 'No Title')

                # Filter for Shorts based on URL containing '/shorts/'
                if '/shorts/' in video_url:
                    full_url = f"{video_url}"
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
        match = re.search(r"/shorts/([^?/]+)", video_url)
        if match:
            video_id = match.group(1)
            return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
        return ""

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

# --------------------------------------------------------------------------
# MAIN WINDOW
# --------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sniperz - Youtube Shorts Bulk Downloader")
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

        # Top row (1): channel selection + scrape
        top_layout = QHBoxLayout()
        label = QLabel("Select channel:")
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("All Channels")
        for c in ALL_CHANNELS:
            self.channel_combo.addItem(c)
        self.channel_combo.setFixedHeight(40)  # Increased height

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

        # top_layout => channel label, combo, Scrape
        top_layout.addWidget(label)
        top_layout.addWidget(self.channel_combo)
        top_layout.addWidget(self.scrape_button)

        # Top row (2): download folder + browse button
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

        # Row for Export CSV & Download Videos
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

        action_layout.addWidget(self.export_button)
        action_layout.addWidget(self.download_button)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(25)  # Slightly increased height

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

        # Store scraped data
        self.scraped_data = []
        self.current_row = 0  # To keep track of table rows

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

                # Clear existing combo items except 'All Channels'
                all_text = self.channel_combo.itemText(0)
                self.channel_combo.clear()
                self.channel_combo.addItem(all_text)
                for line in lines:
                    line = line.strip()
                    if line:
                        self.channel_combo.addItem(line)

                logger.info(f"Loaded {len(lines)} channel URLs from file: {file_path}")
            except Exception as e:
                logger.error(f"Error loading channels from file: {e}")

    # ---------------------------------------------------------
    # SCRAPE BUTTON
    # ---------------------------------------------------------
    def handle_scrape(self):
        logger.info("Scrape button clicked. Starting scrape process...")

        # Disable buttons to prevent multiple operations
        self.scrape_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.channel_combo.setEnabled(False)

        # Change button text to indicate scraping
        self.scrape_button.setText("Scraping...")

        # Clear table & reset
        self.results_table.setRowCount(0)
        self.progress_bar.setValue(0)
        self.scraped_data = []
        self.current_row = 0

        selected = self.channel_combo.currentText()
        if selected == "All Channels":
            channels_to_scrape = ALL_CHANNELS
        else:
            channels_to_scrape = [selected]

        logger.info(f"Channels to scrape: {channels_to_scrape}")

        # Initialize ScrapeWorker with headless=True
        self.scrape_worker = ScrapeWorker(channels_to_scrape, headless=True)
        self.scrape_worker.videoScraped.connect(self.add_video_to_table)
        self.scrape_worker.progressUpdated.connect(self.update_progress)
        self.scrape_worker.done.connect(self.scrape_finished)
        self.scrape_worker.start()

    def scrape_finished(self):
        """Handle actions after scraping is complete."""
        logger.info("Scraping completed.")
        self.scrape_button.setEnabled(True)
        self.browse_button.setEnabled(True)
        self.channel_combo.setEnabled(True)
        self.scrape_button.setText("Scrape")
        logger.info("Ready for next operation.")

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

        try:
            resp = requests.get(thumb_url, timeout=5)
            if resp.status_code == 200:
                img_data = resp.content
                pixmap = QPixmap()
                pixmap.loadFromData(img_data)
                pixmap = pixmap.scaled(
                    80, 60,  # Smaller thumbnail size
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                thumb_item.setData(Qt.ItemDataRole.DecorationRole, pixmap)
            else:
                logger.warning(
                    f"Thumbnail request failed (status={resp.status_code}): {thumb_url}"
                )
        except Exception as e:
            logger.warning(f"Could not load thumbnail: {thumb_url}. Error: {e}")

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

        # Enable download and export buttons if data exists
        if len(self.scraped_data) > 0:
            self.download_button.setEnabled(True)
            self.export_button.setEnabled(True)

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
        self.channel_combo.setEnabled(False)

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
        self.channel_combo.setEnabled(True)
        self.download_button.setText("Download Videos")
        logger.info("Ready for next operation.")

# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    logger.info("Sniperz - Youtube Shorts Bulk Downloader GUI is now visible. Ready to scrape or download.")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
