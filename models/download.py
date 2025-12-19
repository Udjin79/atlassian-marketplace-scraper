"""Data model for download status tracking."""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


@dataclass
class DownloadStatus:
    """Represents the download status of an app version."""

    app_key: str
    version_id: str
    status: str  # 'pending', 'in_progress', 'completed', 'failed'
    downloaded_bytes: int = 0
    total_bytes: int = 0
    error_message: Optional[str] = None
    retry_count: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        """Create DownloadStatus instance from dictionary."""
        return cls(**data)

    def mark_started(self):
        """Mark download as started."""
        self.status = 'in_progress'
        self.started_at = datetime.now().isoformat()

    def mark_completed(self, file_path):
        """Mark download as completed."""
        self.status = 'completed'
        self.completed_at = datetime.now().isoformat()
        self.downloaded_bytes = self.total_bytes

    def mark_failed(self, error_message):
        """Mark download as failed."""
        self.status = 'failed'
        self.error_message = error_message
        self.retry_count += 1

    def get_progress_percentage(self):
        """Calculate download progress as percentage."""
        if self.total_bytes == 0:
            return 0
        return (self.downloaded_bytes / self.total_bytes) * 100
