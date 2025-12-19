"""Rate limiter for API requests."""

import time
from datetime import datetime, timedelta
from collections import deque


class RateLimiter:
    """Rate limiter to control API request frequency."""

    def __init__(self, delay=0.5, requests_per_minute=None):
        """
        Initialize rate limiter.

        Args:
            delay: Minimum delay between requests in seconds
            requests_per_minute: Maximum requests per minute (optional)
        """
        self.delay = delay
        self.requests_per_minute = requests_per_minute
        self.last_request_time = None
        self.request_times = deque(maxlen=requests_per_minute if requests_per_minute else 100)

    def wait_if_needed(self):
        """Wait if necessary to respect rate limits."""
        now = time.time()

        # Simple delay-based rate limiting
        if self.last_request_time is not None:
            elapsed = now - self.last_request_time
            if elapsed < self.delay:
                sleep_time = self.delay - elapsed
                time.sleep(sleep_time)
                now = time.time()

        # Requests per minute limiting (if configured)
        if self.requests_per_minute:
            # Remove requests older than 1 minute
            cutoff_time = now - 60
            while self.request_times and self.request_times[0] < cutoff_time:
                self.request_times.popleft()

            # If at capacity, wait until oldest request expires
            if len(self.request_times) >= self.requests_per_minute:
                sleep_time = 60 - (now - self.request_times[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    now = time.time()

            self.request_times.append(now)

        self.last_request_time = now

    def adaptive_delay(self, status_code):
        """Adjust delay based on HTTP response status code."""
        if status_code == 429:  # Too Many Requests
            self.delay = min(self.delay * 2, 10.0)  # Double delay, max 10s
            print(f"⚠️ Rate limited (429). Increasing delay to {self.delay}s")
        elif status_code >= 500:  # Server errors
            self.delay = min(self.delay * 1.5, 5.0)  # Increase delay, max 5s
            print(f"⚠️ Server error ({status_code}). Increasing delay to {self.delay}s")
        elif status_code == 200 and self.delay > 0.5:
            # Gradually decrease delay on success
            self.delay = max(self.delay * 0.9, 0.5)
