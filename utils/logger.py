"""Logging configuration for the marketplace scraper."""

import logging
import os
from config import settings


def setup_logging():
    """Configure logging for scraper, downloads, and failures."""

    # Create logs directory if it doesn't exist
    os.makedirs(settings.LOGS_DIR, exist_ok=True)

    # Scraper log
    scraper_handler = logging.FileHandler(
        os.path.join(settings.LOGS_DIR, 'scraper.log')
    )
    scraper_handler.setLevel(logging.INFO)
    scraper_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    )

    # Download log
    download_handler = logging.FileHandler(
        os.path.join(settings.LOGS_DIR, 'download.log')
    )
    download_handler.setLevel(logging.INFO)
    download_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    )

    # Failed downloads log (errors only)
    failed_handler = logging.FileHandler(
        os.path.join(settings.LOGS_DIR, 'failed_downloads.log')
    )
    failed_handler.setLevel(logging.ERROR)
    failed_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(message)s')
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    # Add handlers
    root_logger.addHandler(scraper_handler)

    # Configure specific loggers
    scraper_logger = logging.getLogger('scraper')
    scraper_logger.addHandler(scraper_handler)

    download_logger = logging.getLogger('download')
    download_logger.addHandler(download_handler)
    download_logger.addHandler(failed_handler)

    return root_logger


def get_logger(name):
    """Get a logger instance by name."""
    return logging.getLogger(name)
