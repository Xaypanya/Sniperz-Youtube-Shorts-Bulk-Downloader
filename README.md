![Youtube Shorts Downloader](https://raw.githubusercontent.com/Xaypanya/Sniperz-Youtube-Shorts-Bulk-Downloader/refs/heads/main/sniperz_icon.png)

# Sniperz - YouTube Shorts Bulk Downloader

## Overview
**Sniperz** is a robust GUI application designed for efficient bulk downloading of YouTube Shorts. Built with PyQt6 and powered by `yt-dlp`, Sniperz offers seamless video scraping, downloading, and management capabilities in a user-friendly interface.

## Features
- **Bulk Video Scraping:** Extract titles, URLs, and thumbnails from YouTube Shorts channels.
- **Multi-threaded Downloads:** Download up to 5 videos simultaneously for efficiency.
- **Asynchronous Thumbnails:** Load video thumbnails without blocking the interface.
- **Custom Output Directory:** Easily select and save downloaded videos to your preferred location.
- **CSV Export:** Save scraped video details (title, URL, thumbnail URL) in CSV format.
- **Comprehensive Logs:** View real-time logs for monitoring and debugging.
- **Modern GUI:** Dark-themed, responsive interface for enhanced usability.

## Screenshot
![Youtube Shorts Bulk Downloader](https://raw.githubusercontent.com/Xaypanya/Sniperz-Youtube-Shorts-Bulk-Downloader/refs/heads/main/screenshot.png)

## Technologies Used
- **Python:** Core programming language.
- **PyQt6:** For building the graphical user interface.
- **yt-dlp:** Efficient video scraping and downloading library.
- **Requests:** Fetches thumbnails asynchronously.

## Installation

### Prerequisites
- Python 3.9 or later.

### Installation Steps
1. Clone the repository:
   ```bash
   git clone https://github.com/Xaypanya/Sniperz-Youtube-Shorts-Bulk-Downloader.git
   cd Sniperz-Youtube-Shorts-Bulk-Downloader
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python sniperz.py
   ```

## Usage

1. **Enter Channel URLs:**
   - Input one or more YouTube Shorts channel URLs in the format:
     ```
     https://www.youtube.com/@ChannelName/shorts
     ```

2. **Scrape Videos:**
   - Click the **Scrape** button to extract video details. The results will populate in the table.

3. **Select Download Folder:**
   - Use the **Browse** button to choose the folder for saving downloaded videos.

4. **Download Videos:**
   - Click the **Download Videos** button to start downloading.

5. **Export to CSV (Optional):**
   - Save the list of scraped videos by clicking the **Export CSV** button.

## File Structure
```
sniperz-downloader/
├── sniperz_icon.png/        # Icons
├── main.py                  # Main application file
├── requirements.txt         # Dependency file
└── README.md                # Project documentation
```

## Known Issues
- Thumbnails may fail to load for unavailable videos.
- Invalid channel URLs will not be processed.
- A stable internet connection is required for scraping and downloading.

## Contributing
We welcome contributions to enhance Sniperz! To contribute:
1. Fork the repository.
2. Create a feature branch.
3. Commit your changes with clear messages.
4. Submit a pull request.
---

Enjoy seamless bulk downloading with Sniperz! 🚀