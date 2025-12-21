"""Logging configuration for the marketplace scraper with log rotation."""

import logging
import os
import shutil
from logging.handlers import RotatingFileHandler
from config import settings

# Maximum log file size: 5 MB
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB in bytes
BACKUP_COUNT = 5  # Keep 5 backup files


class SafeRotatingFileHandler(RotatingFileHandler):
    """
    RotatingFileHandler with Windows-safe rotation.
    Handles PermissionError when file is locked by another process.
    """
    
    def doRollover(self):
        """
        Do a rollover, as described in __init__().
        Windows-safe version that handles file locking.
        """
        if self.stream:
            self.stream.close()
            self.stream = None
        
        # Check if file exists and needs rotation
        if os.path.exists(self.baseFilename):
            # Check file size
            try:
                if os.path.getsize(self.baseFilename) < self.maxBytes:
                    # File is not large enough, reopen it
                    self.stream = self._open()
                    return
            except OSError:
                # Can't check size, reopen file
                self.stream = self._open()
                return
            
            # File needs rotation
            dfn = self.baseFilename + ".1"
            
            # Remove oldest backup if exists
            oldest_backup = f"{self.baseFilename}.{self.backupCount}"
            if os.path.exists(oldest_backup):
                try:
                    os.remove(oldest_backup)
                except OSError:
                    pass  # Ignore if can't remove
            
            # Rotate existing backups
            for i in range(self.backupCount - 1, 0, -1):
                sfn = f"{self.baseFilename}.{i}"
                dfn = f"{self.baseFilename}.{i + 1}"
                if os.path.exists(sfn):
                    try:
                        if os.path.exists(dfn):
                            os.remove(dfn)
                        os.rename(sfn, dfn)
                    except OSError:
                        pass  # Ignore if can't rename (file might be locked)
            
            # Rotate main file
            dfn = self.baseFilename + ".1"
            try:
                # Try rename first (fastest)
                os.rename(self.baseFilename, dfn)
            except OSError:
                # If rename fails (file locked), try copy + delete
                try:
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    shutil.copy2(self.baseFilename, dfn)
                    # Try to truncate original file instead of deleting
                    try:
                        with open(self.baseFilename, 'w') as f:
                            f.truncate(0)
                    except OSError:
                        pass  # If can't truncate, just continue
                except OSError:
                    # If all fails, just continue - log will append to existing file
                    pass
        
        # Open new file
        self.stream = self._open()


def _get_rotating_handler(log_file: str, level: int = logging.INFO, formatter: logging.Formatter = None) -> SafeRotatingFileHandler:
    """
    Create a rotating file handler with 5 MB max size (Windows-safe).
    
    Args:
        log_file: Path to log file
        level: Logging level
        formatter: Log formatter (optional)
        
    Returns:
        SafeRotatingFileHandler instance
    """
    handler = SafeRotatingFileHandler(
        log_file,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    handler.setLevel(level)
    if formatter is None:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    return handler


def setup_logging():
    """Configure logging for scraper, downloads, and failures with rotation."""

    # Create logs directory if it doesn't exist
    os.makedirs(settings.LOGS_DIR, exist_ok=True)

    # Scraper log with rotation
    scraper_handler = _get_rotating_handler(
        os.path.join(settings.LOGS_DIR, 'scraper.log'),
        level=logging.INFO
    )

    # Download log with rotation
    download_handler = _get_rotating_handler(
        os.path.join(settings.LOGS_DIR, 'download.log'),
        level=logging.INFO
    )

    # Failed downloads log (errors only) with rotation
    failed_handler = _get_rotating_handler(
        os.path.join(settings.LOGS_DIR, 'failed_downloads.log'),
        level=logging.ERROR,
        formatter=logging.Formatter('%(asctime)s - %(message)s')
    )

    # Description downloader log with rotation
    description_handler = _get_rotating_handler(
        os.path.join(settings.LOGS_DIR, 'description_downloader.log'),
        level=logging.INFO
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
    
    description_logger = logging.getLogger('description_downloader')
    description_logger.propagate = False
    description_logger.addHandler(description_handler)
    
    # Error logger for unhandled exceptions
    error_handler = _get_rotating_handler(
        os.path.join(settings.LOGS_DIR, 'errors.log'),
        level=logging.ERROR,
        formatter=logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    )
    error_logger = logging.getLogger('error')
    error_logger.propagate = False
    error_logger.addHandler(error_handler)
    error_logger.setLevel(logging.ERROR)
    
    # Set up exception hook to log all unhandled exceptions
    import sys
    def exception_handler(exc_type, exc_value, exc_traceback):
        """Log all unhandled exceptions."""
        if issubclass(exc_type, KeyboardInterrupt):
            # Allow KeyboardInterrupt to work normally
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        error_logger.error(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback)
        )
    
    sys.excepthook = exception_handler

    return root_logger


def get_logger(name):
    """Get a logger instance by name."""
    return logging.getLogger(name)
