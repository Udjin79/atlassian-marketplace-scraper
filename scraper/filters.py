"""Filters for apps and versions."""

from datetime import datetime, timedelta
from typing import List, Dict
from config import settings
from config.products import ALLOWED_HOSTING


def filter_by_date(versions: List[Dict], days: int = None) -> List[Dict]:
    """
    Filter versions by release date.

    Args:
        versions: List of version dictionaries
        days: Number of days from today (default from settings)

    Returns:
        Filtered list of versions
    """
    if days is None:
        days = settings.VERSION_AGE_LIMIT_DAYS

    cutoff_date = datetime.now() - timedelta(days=days)
    filtered = []

    for version in versions:
        release_date_str = version.get('release_date', '')

        # If no release date, skip it (will be handled by version_name pairing in scraper)
        if not release_date_str:
            continue

        try:
            # Try parsing different date formats
            release_date = None
            formats = [
                '%Y-%m-%dT%H:%M:%S.%fZ',
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d'
            ]

            for fmt in formats:
                try:
                    release_date = datetime.strptime(release_date_str, fmt)
                    break
                except ValueError:
                    continue

            if release_date and release_date >= cutoff_date:
                filtered.append(version)

        except Exception:
            # If date parsing fails, include the version to be safe
            filtered.append(version)

    return filtered


def filter_by_hosting(versions: List[Dict], allowed_hosting: List[str] = None) -> List[Dict]:
    """
    Filter versions by hosting type (server/datacenter only).

    Args:
        versions: List of version dictionaries
        allowed_hosting: List of allowed hosting types (default: server, datacenter)

    Returns:
        Filtered list of versions
    """
    if allowed_hosting is None:
        allowed_hosting = ALLOWED_HOSTING

    filtered = []

    for version in versions:
        hosting_type = version.get('hosting_type', '').lower()

        # If no hosting type specified, include it (might be server)
        if not hosting_type:
            filtered.append(version)
            continue

        if hosting_type in allowed_hosting:
            filtered.append(version)

    return filtered


def filter_by_product(apps: List[Dict], product: str) -> List[Dict]:
    """
    Filter apps by product.

    Args:
        apps: List of app dictionaries
        product: Product key (jira, confluence, etc.)

    Returns:
        Filtered list of apps
    """
    return [app for app in apps
            if product in app.get('products', [])]


def filter_server_datacenter_apps(apps: List[Dict]) -> List[Dict]:
    """
    Filter apps that support server or datacenter hosting.

    Args:
        apps: List of app dictionaries

    Returns:
        Filtered list of apps
    """
    filtered = []

    for app in apps:
        hosting = app.get('hosting', [])
        if any(h in ALLOWED_HOSTING for h in hosting):
            filtered.append(app)

    return filtered
