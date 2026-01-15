"""Download plugin descriptions with images and videos from Atlassian Marketplace."""

import os
import json
import re
import hashlib
import mimetypes
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Union, Union
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin, urlparse
import requests
from requests import HTTPError
from bs4 import BeautifulSoup
from config import settings
from scraper.metadata_store import MetadataStore
from utils.logger import get_logger

logger = get_logger('description_downloader')

API_BASE = "https://marketplace.atlassian.com/rest/2"
MARKETPLACE_BASE = "https://marketplace.atlassian.com"


# Helper functions for marketplace page saving
def _normalize_marketplace_url(url: str) -> str:
    """
    Normalize Marketplace URL to absolute URL.
    
    Args:
        url: Relative or absolute URL
        
    Returns:
        Absolute URL
    """
    # Relative link from JSON like "/apps/6820/..."
    if url.startswith("/"):
        return f"{MARKETPLACE_BASE}{url}"
    # Without scheme
    if not url.lower().startswith(("http://", "https://")):
        return f"{MARKETPLACE_BASE}/{url.lstrip('/')}"
    return url


def _should_skip_resource(url: str) -> bool:
    """
    Check if resource URL should be skipped.
    
    Args:
        url: Resource URL
        
    Returns:
        True if should skip
    """
    low = url.lower()
    return (
        low.startswith("data:")
        or low.startswith("javascript:")
        or low.startswith("#")
        or low.startswith("mailto:")
        or low.startswith("tel:")
    )


def _safe_filename_from_url(url: str, content_type: Optional[str] = None) -> str:
    """
    Generate safe filename from URL.
    
    Args:
        url: Resource URL
        content_type: Optional content type from response headers
        
    Returns:
        Safe filename
    """
    parsed = urlparse(url)
    base = os.path.basename(parsed.path) or "resource"

    # If no extension - try to guess from content-type
    root, ext = os.path.splitext(base)
    if not ext and content_type:
        ct = content_type.split(";")[0].strip().lower()
        guessed = mimetypes.guess_extension(ct) or ""
        if guessed:
            ext = guessed
            base = f"{base}{ext}"

    # Collision protection: add short URL hash
    h = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    root, ext = os.path.splitext(base)
    base = f"{root}_{h}{ext}"

    # Remove dangerous characters for Windows/FS
    base = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in base)
    return base


def _worker_process_batch(batch):
    """
    Worker function for multiprocessing - processes a batch of apps.
    Each worker process creates its own browser and reuses it for all items in the batch.
    Must be at module level to be picklable.
    """
    if not batch:
        return {'success': 0, 'fail': 0, 'skip': 0}

    success = 0
    fail = 0
    skip = 0
    total = batch[0]['total']  # Total across all batches
    use_full_page = batch[0]['use_full_page']

    # Create downloader with its own browser for this process
    downloader = DescriptionDownloader()

    # Set up browser reuse for this process
    browser_manager = None
    if use_full_page:
        try:
            from scraper.page_saver_integrated import PlaywrightBrowserManager
            browser_manager = PlaywrightBrowserManager()
            browser_manager.__enter__()
            downloader._playwright_page = browser_manager.page
            if downloader._playwright_page:
                logger.debug(f"Worker process started browser")
        except Exception as e:
            logger.warning(f"Worker failed to start browser: {e}")

    try:
        for item in batch:
            addon_key = item['addon_key']
            idx = item['idx']

            # Skip if description already exists
            if downloader.description_exists(addon_key, use_full_page=use_full_page):
                skip += 1
                print(f"{idx}/{total} [SKIP] {addon_key} (already exists)", flush=True)
                logger.debug(f"[SKIP] Description already exists: {addon_key}")
                continue

            try:
                json_path, html_path = downloader.download_description(
                    addon_key,
                    download_media=item['download_media'],
                    marketplace_url=item['marketplace_url'] if use_full_page else None
                )

                if json_path or html_path:
                    success += 1
                    print(f"{idx}/{total} [OK] {addon_key}", flush=True)
                    logger.info(f"[OK] Success: {addon_key}")
                else:
                    fail += 1
                    print(f"{idx}/{total} [FAIL] {addon_key}", flush=True)
                    logger.warning(f"[ERROR] Failed: {addon_key}")

            except Exception as e:
                fail += 1
                print(f"{idx}/{total} [ERROR] {addon_key}", flush=True)
                logger.error(f"[ERROR] Exception downloading {addon_key}: {e}")

    finally:
        downloader._playwright_page = None
        if browser_manager:
            browser_manager.__exit__(None, None, None)

    return {'success': success, 'fail': fail, 'skip': skip}


class DescriptionDownloader:
    """Downloads plugin descriptions with media from Atlassian Marketplace."""

    def __init__(self, metadata_store: Optional[MetadataStore] = None):
        """
        Initialize description downloader.

        Args:
            metadata_store: Optional MetadataStore instance
        """
        self.store = metadata_store or MetadataStore()
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        })

        # Add authentication if available
        if settings.MARKETPLACE_USERNAME and settings.MARKETPLACE_API_TOKEN:
            self.session.auth = (settings.MARKETPLACE_USERNAME, settings.MARKETPLACE_API_TOKEN)

        # Base directory for descriptions (can be configured via DESCRIPTIONS_DIR env var)
        self.descriptions_dir = os.path.abspath(settings.DESCRIPTIONS_DIR)  # Ensure absolute path
        os.makedirs(self.descriptions_dir, exist_ok=True)
        logger.debug(f"Descriptions directory: {self.descriptions_dir}")

        # Playwright page for reuse across multiple downloads (set by download_all_descriptions)
        self._playwright_page = None

    def description_exists(self, addon_key: str, use_full_page: bool = True) -> bool:
        """
        Check if description for an app already exists.

        Args:
            addon_key: App key
            use_full_page: Check for full page (index.html) or API description

        Returns:
            True if description exists
        """
        addon_dir = addon_key.replace('.', '_')
        if use_full_page:
            # Check for full_page/index.html
            full_page_path = Path(self.descriptions_dir) / addon_dir / 'full_page' / 'index.html'
            return full_page_path.exists()
        else:
            # Check for description.json (API mode)
            json_path = Path(self.descriptions_dir) / addon_dir / 'description.json'
            return json_path.exists()

    def _fetch(self, url: str, params: Optional[Dict] = None, log_errors: bool = True) -> Dict:
        """Fetch data from API."""
        try:
            response = self.session.get(url, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"value": data}
        except HTTPError as e:
            # Log 404s at debug level (expected for optional endpoints)
            if e.response is not None and e.response.status_code == 404:
                logger.debug(f"Not found (404): {url}")
            elif log_errors:
                logger.error(f"Error fetching {url}: {str(e)}")
            raise
        except Exception as e:
            if log_errors:
                logger.error(f"Error fetching {url}: {str(e)}")
            raise

    def _fetch_with_fallback(
        self,
        primary_url: str,
        fallback_url: Optional[str] = None,
        params: Optional[Dict] = None
    ) -> Dict:
        """Fetch with fallback URL. Silently tries fallbacks on 404 (these endpoints are optional)."""
        try:
            return self._fetch(primary_url, params=params, log_errors=False)
        except HTTPError as exc:
            if exc.response is None or exc.response.status_code != 404:
                raise

            candidates = []
            if fallback_url:
                candidates.append((fallback_url, params))
            if params and "locale" in params:
                stripped = {k: v for k, v in params.items() if k != "locale"}
                candidates.append((primary_url, stripped))
                if fallback_url:
                    candidates.append((fallback_url, stripped))

            for candidate_url, candidate_params in candidates:
                try:
                    return self._fetch(candidate_url, params=candidate_params, log_errors=False)
                except HTTPError:
                    continue

            # Log once at debug level when all fallbacks exhausted
            logger.debug(f"Optional endpoint not available: {primary_url}")
            return {"error": "not-found", "url": primary_url, "fallback_url": fallback_url}

    def _get_versions(self, addon_key: str, hosting: str = "datacenter", limit: int = 100) -> List[Dict]:
        """Get all versions for an addon."""
        params = {"hosting": hosting, "limit": limit, "offset": 0}
        items = []
        while True:
            url = f"{API_BASE}/addons/{addon_key}/versions"
            try:
                response = self.session.get(url, params=params, timeout=60)
                response.raise_for_status()
                payload = response.json()
                embedded = (payload.get("_embedded") or {}).get("versions", []) or []
                items.extend(embedded)
                next_href = ((payload.get("_links") or {}).get("next") or {}).get("href")
                if not next_href:
                    break
                params["offset"] = params.get("offset", 0) + params.get("limit", limit)
            except Exception as e:
                logger.error(f"Error fetching versions for {addon_key}: {str(e)}")
                break
        return items

    def _pick_version(self, versions: List[Dict], wanted: Optional[str] = None) -> Optional[Dict]:
        """Pick version from list."""
        if not versions:
            return None
        if not wanted:
            return versions[0]
        target = wanted.strip().lower()
        for entry in versions:
            if (entry.get("name") or "").strip().lower() == target:
                return entry
        for entry in versions:
            if (entry.get("name") or "").strip().lower().startswith(target):
                return entry
        return None

    def _render_html(self, payload: Dict) -> str:
        """Render HTML from payload."""
        addon = payload.get("addon", {})
        version_info = payload.get("version", {})
        overview = payload.get("overview", {})
        highlights = payload.get("highlights", {})
        media = payload.get("media", {})

        version_name = version_info.get("name") or "latest"
        release_date = (
            version_info.get("raw", {}).get("release", {}).get("date")
            or version_info.get("released_at")
            or "N/A"
        )

        rating = addon.get("_embedded", {}).get("reviews", {}).get("averageStars")
        reviews_count = addon.get("_embedded", {}).get("reviews", {}).get("count")

        summary = addon.get("summary") or ""
        tagline = addon.get("tagLine") or ""
        legacy_description = addon.get("legacy", {}).get("description")
        # New structure: overview.moreDetails, old structure: overview.body
        overview_body = overview.get("moreDetails") or overview.get("body") or overview.get("content")
        description_html = overview_body or legacy_description or "<p>Description not available.</p>"

        # Release notes from new structure (extracted for potential future use)
        _release_notes = overview.get("releaseNotes", "")  # noqa: F841
        _release_summary = overview.get("releaseSummary", "")  # noqa: F841

        categories = [
            escape(cat.get("name", ""))
            for cat in addon.get("_embedded", {}).get("categories", [])
            if cat.get("name")
        ]
        keywords = [
            escape(tag.get("name", ""))
            for tag in (addon.get("tags", {}) or {}).get("keywords", [])
            if tag.get("name")
        ]

        distribution = addon.get("_embedded", {}).get("distribution", {})
        downloads = distribution.get("downloads")
        installs = distribution.get("totalInstalls")

        vendor = addon.get("_embedded", {}).get("vendor", {}) or {}
        vendor_name = vendor.get("name") or addon.get("vendor", {}).get("name") or "Unknown vendor"
        _vendor_logo = (  # noqa: F841 - extracted for potential future use
            vendor.get("_embedded", {}).get("logo", {}).get("_links", {}).get("image", {}).get("href")
            if isinstance(vendor.get("_embedded", {}), dict)
            else None
        )

        hero_image = addon.get("_embedded", {}).get("banner", {}).get("_links", {}).get("image", {}).get("href")
        logo_image = addon.get("_embedded", {}).get("logo", {}).get("_links", {}).get("image", {}).get("href")

        vendor_links = addon.get("vendorLinks", {}) or {}
        vendor_links_html = ""
        if vendor_links:
            items = []
            for label, url in vendor_links.items():
                if not url:
                    continue
                items.append(f'<li><a href="{escape(url)}" target="_blank" rel="noopener">{escape(label)}</a></li>')
            vendor_links_html = "<ul class=\"link-list\">" + "\n".join(items) + "</ul>"

        highlight_sections_html = ""
        # New structure: highlights is a list directly from _embedded.highlights
        # Old structure: highlights._embedded.highlightSections[]
        if isinstance(highlights, list) and highlights:
            parts = []
            for section in highlights:
                title = escape(section.get("title") or section.get("heading") or "Highlight")
                body = section.get("body") or section.get("description") or ""
                explanation = section.get("explanation", "")
                parts.append(f'<div class="highlight-block"><h3>{title}</h3>{body}')
                if explanation:
                    parts[-1] += f'<p class="explanation">{escape(explanation)}</p>'
                parts[-1] += '</div>'
            highlight_sections_html = "\n".join(parts)
        elif isinstance(highlights, dict) and "error" not in highlights:
            # Old structure fallback
            sections = highlights.get("_embedded", {}).get("highlightSections", []) or []
            parts = []
            for section in sections:
                title = escape(section.get("title") or section.get("heading") or "Highlight")
                body = section.get("body") or section.get("description") or ""
                parts.append(f'<div class="highlight-block"><h3>{title}</h3>{body}</div>')
            highlight_sections_html = "\n".join(parts)
        else:
            highlight_sections_html = '<p class="muted">Highlight data not available.</p>'

        media_items_html = ""
        if isinstance(media, dict) and "error" not in media:
            # New structure: media.screenshots[] and media.youtubeId
            screenshots = media.get("screenshots", [])
            youtube_id = media.get("youtubeId")

            media_parts = []

            # Add YouTube video if available
            if youtube_id:
                media_parts.append(
                    f'<div class="media-item video">'
                    f'<iframe width="560" height="315" src="https://www.youtube.com/embed/{escape(youtube_id)}" '
                    f'frameborder="0" allowfullscreen></iframe></div>'
                )

            # Add screenshots
            for idx, screenshot in enumerate(screenshots, start=1):
                embedded_image = (screenshot.get("_embedded") or {}).get("image", {})
                image_links = (embedded_image.get("_links") or {})
                href = None
                for key in ["image", "unscaled", "highRes"]:
                    link_data = image_links.get(key, {})
                    if isinstance(link_data, dict) and link_data.get("href"):
                        href = link_data["href"]
                        break
                if href:
                    caption = screenshot.get("caption", f"Screenshot {idx}")
                    media_parts.append(
                        f'<div class="media-item screenshot">'
                        f'<a href="{escape(href)}" target="_blank" rel="noopener">'
                        f'<img src="{escape(href)}" alt="{escape(caption)}" loading="lazy" style="max-width:100%;height:auto;">'
                        f'</a><p class="caption">{escape(caption)}</p></div>'
                    )

            # Old structure fallback
            if not media_parts:
                items = media.get("_embedded", {}).get("media", []) or []
                for idx, item in enumerate(items, start=1):
                    binaries = item.get("_embedded", {}).get("binary", []) or []
                    for binary in binaries:
                        href = binary.get("href")
                        if not href:
                            continue
                        name = binary.get("name") or binary.get("type") or f"media-{idx}"
                        media_parts.append(f'<li><a href="{escape(href)}" target="_blank" rel="noopener">{escape(name)}</a></li>')

            if media_parts:
                # Check if it's old list format or new div format
                if media_parts and media_parts[0].startswith('<li>'):
                    media_items_html = "<ul class=\"link-list\">" + "\n".join(media_parts) + "</ul>"
                else:
                    media_items_html = '<div class="media-gallery">' + "\n".join(media_parts) + '</div>'
            else:
                media_items_html = '<p class="muted">Media not available.</p>'
        else:
            media_items_html = '<p class="muted">Media not available.</p>'

        categories_html = ", ".join(categories) if categories else "—"
        keywords_html = ", ".join(keywords) if keywords else "—"

        rating_html = (
            f"{rating:.2f} ⭐ ({reviews_count} reviews)" if rating and reviews_count else "No rating"
        )
        downloads_html = f"{downloads:,}" if isinstance(downloads, int) else "—"
        installs_html = f"{installs:,}" if isinstance(installs, int) else "—"

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(addon.get("name", "Addon"))} — Marketplace snapshot</title>
  <style>
    body {{ font-family: "Segoe UI", Arial, sans-serif; margin: 0; padding: 0; background: #f4f6fb; color: #1f2933; }}
    header {{ background: #0f5ef7; color: #fff; padding: 2.5rem 2rem; position: relative; }}
    header img.hero {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0.25; }}
    header .overlay {{ position: relative; max-width: 960px; margin: 0 auto; }}
    main {{ padding: 2rem; max-width: 960px; margin: 0 auto; }}
    .card {{ background: #fff; border-radius: 16px; padding: 1.6rem; box-shadow: 0 20px 45px rgba(15, 23, 56, 0.12); margin-bottom: 1.8rem; }}
    .meta-grid {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }}
    .meta-item span {{ display: block; font-size: 0.78rem; text-transform: uppercase; color: #73819a; letter-spacing: 0.08em; margin-bottom: 0.3rem; }}
    .muted {{ color: #73819a; font-style: italic; }}
    footer {{ padding: 2rem; text-align: center; color: #73819a; font-size: 0.85rem; }}
    .logo {{ max-width: 80px; border-radius: 12px; box-shadow: 0 6px 18px rgba(15, 23, 56, 0.15); }}
    .row {{ display: flex; gap: 1.5rem; align-items: center; flex-wrap: wrap; }}
    h1 {{ margin: 0; font-size: 2.5rem; }}
    h2 {{ margin-top: 0; }}
    .tagline {{ font-size: 1.2rem; margin-top: 0.5rem; }}
    .link-list {{ margin: 0; padding-left: 1.1rem; }}
    .link-list li {{ margin-bottom: 0.35rem; }}
    .highlight-block {{ border-left: 4px solid #0f5ef7; padding: 0.85rem 1rem; margin-bottom: 1rem; background: rgba(15, 94, 247, 0.08); border-radius: 10px; }}
    .highlight-block h3 {{ margin-top: 0; }}
    img {{ max-width: 100%; height: auto; }}
    video {{ max-width: 100%; height: auto; }}
  </style>
</head>
<body>
  <header>
    {"<img class='hero' src='" + escape(hero_image) + "' alt='Banner'>" if hero_image else ""}
    <div class="overlay">
      <div class="row">
        {"<img class='logo' src='" + escape(logo_image) + "' alt='Logo'>" if logo_image else ""}
        <div>
          <h1>{escape(addon.get("name", "Addon"))}</h1>
          {"<p class='tagline'>" + escape(tagline) + "</p>" if tagline else ""}
        </div>
      </div>
    </div>
  </header>
  <main>
    <section class="card">
      <h2>Summary</h2>
      {"<p>" + escape(summary) + "</p>" if summary else "<p class='muted'>No description available.</p>"}
      <div class="meta-grid">
        <div class="meta-item"><span>Version</span>{escape(str(version_name))}</div>
        <div class="meta-item"><span>Release Date</span>{escape(release_date)}</div>
        <div class="meta-item"><span>Rating</span>{rating_html}</div>
        <div class="meta-item"><span>Downloads</span>{downloads_html}</div>
        <div class="meta-item"><span>Installs</span>{installs_html}</div>
        <div class="meta-item"><span>Categories</span>{categories_html}</div>
        <div class="meta-item"><span>Keywords</span>{keywords_html}</div>
      </div>
    </section>

    <section class="card">
      <h2>Description</h2>
      {description_html}
    </section>

    <section class="card">
      <h2>Highlights</h2>
      {highlight_sections_html}
    </section>

    <section class="card">
      <h2>Media</h2>
      {media_items_html}
    </section>

    <section class="card">
      <h2>Vendor</h2>
      <p><strong>{escape(vendor_name)}</strong></p>
      {vendor_links_html or "<p class='muted'>Vendor links not available.</p>"}
    </section>
  </main>
  <footer>
    Snapshot from Atlassian Marketplace, fetched {escape(payload.get("fetched_at", ""))}.
  </footer>
</body>
</html>
"""
        return html_content

    def download_description(
        self,
        addon_key: str,
        version_name: Optional[str] = None,
        hosting: str = "datacenter",
        locale: str = "en_US",
        download_media: bool = True,
        marketplace_url: Optional[str] = None,
        download_all_hosting: bool = False
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Download description for an app.

        Args:
            addon_key: App key
            version_name: Optional version name (default: latest)
            hosting: Hosting type (datacenter/server/cloud)
            locale: Locale
            download_media: Download media files (images/videos)
            marketplace_url: Optional full Marketplace URL (if provided, downloads full page)

        Returns:
            Tuple of (json_path, html_path) or (None, None) on error
        """
        # If download_all_hosting is True, download for hosting types (datacenter first, then server if datacenter not available)
        if download_all_hosting and marketplace_url:
            # Priority: datacenter > server (cloud is skipped)
            hosting_types = ["datacenter", "server"]
            results = []
            
            print(f"  → Checking available hosting types (datacenter, server)...")
            import sys
            sys.stdout.flush()
            
            # Try datacenter first
            datacenter_result = None
            for idx, htype in enumerate(hosting_types, 1):
                print(f"\n  [{idx}/{len(hosting_types)}] Processing {htype.upper()} version...")
                sys.stdout.flush()
                
                # Modify URL to include hosting type
                url_with_hosting = marketplace_url
                if "hosting=" in url_with_hosting:
                    url_with_hosting = re.sub(r'hosting=[^&]+', f'hosting={htype}', url_with_hosting)
                else:
                    separator = "&" if "?" in url_with_hosting else "?"
                    url_with_hosting = f"{url_with_hosting}{separator}hosting={htype}"
                
                logger.info(f"Downloading description for {addon_key} (hosting: {htype})")
                print(f"    URL: {url_with_hosting}")
                sys.stdout.flush()
                
                # Save to hosting-specific subdirectory
                hosting_output_dir = Path(self.descriptions_dir) / addon_key.replace('.', '_') / 'full_page' / htype
                hosting_output_dir.mkdir(parents=True, exist_ok=True)
                print(f"    Output: {hosting_output_dir}")
                sys.stdout.flush()
                
                try:
                    # Create a temporary marketplace_url with hosting type for this iteration
                    result = self.download_description(
                        addon_key=addon_key,
                        version_name=version_name,
                        hosting=htype,
                        locale=locale,
                        download_media=download_media,
                        marketplace_url=url_with_hosting,
                        download_all_hosting=False  # Prevent recursion
                    )
                    
                    if result[0] or result[1]:
                        print(f"    ✓ {htype.upper()} version downloaded successfully")
                        sys.stdout.flush()
                        results.append(result)
                        
                        # If datacenter succeeded, skip server
                        if htype == "datacenter":
                            datacenter_result = result
                            print(f"\n  → Data Center version found and downloaded, skipping server version")
                            sys.stdout.flush()
                            break
                    else:
                        print(f"    ⚠ {htype.upper()} version download failed")
                        sys.stdout.flush()
                        results.append((None, None))
                except KeyboardInterrupt:
                    print(f"\n    [!] Download interrupted by user")
                    raise
                except Exception as e:
                    print(f"    ✗ {htype.upper()} version failed: {str(e)}")
                    sys.stdout.flush()
                    results.append((None, None))
            
            print(f"\n  → Completed hosting types check")
            sys.stdout.flush()
            
            # Return the first successful result (prefer datacenter)
            if datacenter_result and (datacenter_result[0] or datacenter_result[1]):
                return datacenter_result
            
            for result in results:
                if result[0] or result[1]:
                    return result
            return None, None
        
        # If marketplace_url provided, download full page instead
        if marketplace_url:
            # Try full page saver from old version (RECOMMENDED - uses complete page_saver logic)
            try:
                from scraper.page_saver_integrated import save_webpage_full
                
                output_dir = Path(self.descriptions_dir) / addon_key.replace('.', '_') / 'full_page'
                output_dir.mkdir(parents=True, exist_ok=True)
                
                html_path = output_dir / 'index.html'
                assets_dir = output_dir / 'assets'
                
                print(f"    → Downloading full page HTML...")
                print(f"      Method: page_saver_integrated (Playwright)")
                import sys
                sys.stdout.flush()
                
                logger.info(f"Attempting to download full page for {addon_key} using page_saver_integrated")
                logger.debug(f"URL: {marketplace_url}, Output: {html_path}, Assets: {assets_dir}")
                
                print(f"      Loading page with Playwright (this may take 10-30 seconds)...")
                sys.stdout.flush()
                result = save_webpage_full(
                    url=marketplace_url,
                    output=str(html_path),
                    offline=True,
                    assets_dir=str(assets_dir),
                    timeout=120,
                    wait_seconds=10,
                    session=self.session,
                    playwright_page=self._playwright_page  # Reuse browser if available
                )
                
                if result and Path(result.output_html).exists():
                    file_size = Path(result.output_html).stat().st_size
                    size_mb = file_size / (1024 * 1024)
                    print(f"      ✓ Full page downloaded: {size_mb:.1f} MB")
                    sys.stdout.flush()
                    logger.info(f"Successfully downloaded full page for {addon_key} to {result.output_html}")
                    
                    # Extract documentation URL from downloaded HTML
                    documentation_url = None
                    try:
                        with open(result.output_html, 'r', encoding='utf-8', errors='replace') as f:
                            html_content = f.read()
                            documentation_url = self._extract_documentation_url_from_html(html_content)
                            if documentation_url:
                                logger.info(f"Extracted documentation URL from full page: {documentation_url}")
                    except Exception as e:
                        logger.warning(f"Failed to extract documentation URL from full page: {str(e)}")
                    
                    # Also download API description for web interface (with summary and documentation_url)
                    print(f"    → Downloading API description (for web interface)...")
                    sys.stdout.flush()
                    try:
                        api_json_path, api_html_path = self._download_api_description(
                            addon_key, version_name, hosting, locale, download_media, 
                            marketplace_url=marketplace_url, documentation_url=documentation_url
                        )
                        if api_json_path:
                            json_size = api_json_path.stat().st_size if api_json_path.exists() else 0
                            json_kb = json_size / 1024
                            print(f"      ✓ API description downloaded: {json_kb:.1f} KB")
                            sys.stdout.flush()
                            logger.info(f"Also downloaded API description for {addon_key}")
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        print(f"      ⚠ API description failed: {str(e)}")
                        sys.stdout.flush()
                        logger.warning(f"Failed to download API description: {e}")
                    return None, Path(result.output_html)
                else:
                    logger.warning(f"Full page saver returned but file doesn't exist: {result.output_html if result else 'None'}")
            except ImportError as e:
                logger.warning(f"page_saver_integrated not available: {e}, trying Playwright method")
            except Exception as e:
                logger.error(f"Full page saver failed: {str(e)}", exc_info=True)
                logger.warning(f"Trying Playwright method as fallback")
            
            # Fallback: Try Playwright method
            try:
                output_dir = Path(self.descriptions_dir) / addon_key.replace('.', '_') / 'full_page'
                output_dir.mkdir(parents=True, exist_ok=True)
                
                html_path = output_dir / 'index.html'
                
                html_path_result = self.save_marketplace_page_with_playwright(
                    download_url=marketplace_url,
                    save_path=html_path,
                    format='html',
                    wait_seconds=10,
                    timeout=120
                )
                
                if html_path_result and html_path_result.exists():
                    logger.info(f"Successfully downloaded page with Playwright (HTML) for {addon_key}")
                    # Also download API description for web interface
                    try:
                        api_json_path, api_html_path = self._download_api_description(
                            addon_key, version_name, hosting, locale, download_media
                        )
                        if api_json_path:
                            logger.info(f"Also downloaded API description for {addon_key}")
                    except Exception as e:
                        logger.warning(f"Failed to download API description: {e}")
                    return None, html_path_result
            except ImportError:
                logger.warning("Playwright not installed, skipping Playwright method. Install with: pip install playwright && playwright install chromium")
            except Exception as e:
                logger.warning(f"Playwright method failed for {addon_key}: {str(e)}, trying script removal method")
            
            # Fallback: Try script removal method (works offline but may not have JS content)
            try:
                output_dir = Path(self.descriptions_dir) / addon_key.replace('.', '_') / 'full_page'
                html_path_new = output_dir / 'index.html'
                
                html_path_result, assets_dir = self.save_marketplace_plugin_page(
                    download_url=marketplace_url,
                    save_html_path=html_path_new,
                    encoding='utf-8',
                    download_media=download_media,
                    timeout=60
                )
                
                if html_path_result and html_path_result.exists():
                    logger.info(f"Successfully downloaded page (scripts removed) for {addon_key}")
                    return None, html_path_result
            except Exception as e:
                logger.warning(f"save_marketplace_plugin_page failed for {addon_key}: {str(e)}, trying static API method")
            
            # Fallback to static API method (uses REST API)
            try:
                output_dir = Path(self.descriptions_dir) / addon_key.replace('.', '_') / 'full_page'
                html_path_new = output_dir / 'index.html'
                
                html_path_result, assets_dir = self.save_marketplace_plugin_page_static(
                    download_url=marketplace_url,
                    save_html_path=html_path_new,
                    encoding='utf-8',
                    download_media=download_media,
                    addon_key=addon_key,  # We already have it, pass explicitly
                    timeout=60
                )
                
                if html_path_result and html_path_result.exists():
                    logger.info(f"Successfully downloaded static snapshot for {addon_key}")
                    return None, html_path_result
            except Exception as e:
                logger.warning(f"Static snapshot failed for {addon_key}: {str(e)}, trying original method")
            
            # Fallback to original method
            html_path = self.download_full_marketplace_page(
                marketplace_url,
                addon_key,
                download_assets=download_media
            )
            if html_path:
                # Also download API description for web interface
                try:
                    api_json_path, api_html_path = self._download_api_description(
                        addon_key, version_name, hosting, locale, download_media
                    )
                    if api_json_path:
                        logger.info(f"Also downloaded API description for {addon_key}")
                except Exception as e:
                    logger.warning(f"Failed to download API description: {e}")
                return None, html_path
            # Fallback to API if all full page downloads fail
            logger.warning(f"All full page download methods failed, falling back to API for {addon_key}")
        
        # Download API description (always, even if full_page was downloaded)
        try:
            return self._download_api_description(addon_key, version_name, hosting, locale, download_media)
        except Exception as e:
            logger.error(f"Error downloading API description for {addon_key}: {str(e)}")
            return None, None
    
    def _download_api_description(
        self,
        addon_key: str,
        version_name: Optional[str] = None,
        hosting: str = "datacenter",
        locale: str = "en_US",
        download_media: bool = True,
        marketplace_url: Optional[str] = None,
        documentation_url: Optional[str] = None
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Download description from API (internal method).
        
        Returns:
            Tuple of (json_path, html_path) or (None, None) on error
        """
        try:
            # Get versions
            print(f"      Fetching versions from API...")
            import sys
            sys.stdout.flush()
            versions = self._get_versions(addon_key, hosting)
            if not versions:
                logger.warning(f"No versions found for {addon_key}")
                print(f"      ⚠ No versions found")
                sys.stdout.flush()
                return None, None

            picked = self._pick_version(versions, version_name)
            if not picked:
                logger.warning(f"Version '{version_name}' not found for {addon_key}")
                print(f"      ⚠ Version '{version_name}' not found")
                sys.stdout.flush()
                return None, None
            
            version_name_display = picked.get("name", "unknown")
            print(f"      Selected version: {version_name_display}")
            sys.stdout.flush()

            # Extract build number from version self link
            self_href = ((picked.get("_links") or {}).get("self") or {}).get("href", "")
            build_number = None
            if isinstance(self_href, str) and self_href:
                match = re.search(r"/versions/build/(\d+)", self_href)
                if match:
                    build_number = match.group(1)

            # Fallback to version id if no build number
            version_id = build_number or picked.get("id")
            if not version_id:
                logger.error(f"Version ID/build number not found for {addon_key}")
                return None, None

            # Fetch full version details (contains highlights, screenshots, media, text)
            # This single endpoint provides all data that was previously fetched from
            # /overview, /highlights, /media (which don't exist and returned 404)
            print(f"      Fetching version details...")
            sys.stdout.flush()
            version_url = f"{API_BASE}/addons/{addon_key}/versions/build/{version_id}"
            try:
                version_details = self._fetch(version_url, params={"locale": locale})
            except Exception as e:
                logger.warning(f"Failed to fetch version details: {e}")
                version_details = {}

            # Extract data from version details response
            embedded = version_details.get("_embedded", {})
            highlights = embedded.get("highlights", [])
            screenshots = embedded.get("screenshots", [])
            text_data = version_details.get("text", {})

            # Build overview from text data
            overview = {
                "moreDetails": text_data.get("moreDetails", ""),
                "releaseSummary": text_data.get("releaseSummary", ""),
                "releaseNotes": text_data.get("releaseNotes", ""),
            }

            # Build media from screenshots and youtubeId
            media = {
                "screenshots": screenshots,
                "youtubeId": version_details.get("youtubeId"),
            }

            # Also fetch addon info for summary and other metadata
            print(f"      Fetching addon information...")
            sys.stdout.flush()
            addon_url = f"{API_BASE}/addons/{addon_key}"
            addon_info = self._fetch(addon_url, params={"locale": locale, "hosting": hosting, "expand": "details"})

            # Extract summary from addon_info for easy access
            summary = addon_info.get("summary") or addon_info.get("tagLine") or ""

            # Extract vendor documentation link
            # Use provided documentation_url if available (from full page download), otherwise try API
            if not documentation_url:
                # First try version_details.vendorLinks (most reliable source)
                vendor_links = version_details.get("vendorLinks", {}) or {}
                documentation_url = vendor_links.get("documentation")

                # Fall back to addon_info.vendorLinks
                if not documentation_url:
                    vendor_links = addon_info.get("vendorLinks", {}) or {}
                    # Look for documentation link in vendorLinks
                    for key, value in vendor_links.items():
                        if isinstance(value, str) and value:
                            key_lower = key.lower()
                            if 'doc' in key_lower or 'documentation' in key_lower or 'guide' in key_lower:
                                documentation_url = value
                                break

                # Also check in _embedded or other fields
                if not documentation_url:
                    addon_embedded = addon_info.get("_embedded", {})
                    if isinstance(addon_embedded, dict):
                        # Check for documentation in various places
                        for key, value in addon_embedded.items():
                            if isinstance(value, dict) and 'href' in value:
                                key_lower = key.lower()
                                if 'doc' in key_lower or 'documentation' in key_lower:
                                    documentation_url = value.get('href')
                                    break
            
            # If not found in API and not provided, try to extract from HTML page if marketplace_url is available
            if not documentation_url and marketplace_url:
                try:
                    print(f"      Extracting documentation URL from HTML page...")
                    import sys
                    sys.stdout.flush()
                    page_resp = self.session.get(marketplace_url, timeout=30, allow_redirects=True)
                    page_resp.raise_for_status()
                    if page_resp.encoding is None or page_resp.encoding.lower() not in ['utf-8', 'utf8']:
                        page_resp.encoding = 'utf-8'
                    page_html = page_resp.text
                    documentation_url = self._extract_documentation_url_from_html(page_html)
                    if documentation_url:
                        print(f"      ✓ Found documentation URL: {documentation_url}")
                        sys.stdout.flush()
                except Exception as e:
                    logger.warning(f"Failed to extract documentation URL from HTML: {str(e)}")

            payload = {
                "addon_key": addon_key,
                "hosting": hosting,
                "locale": locale,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,  # Add summary at root level for easy access
                "documentation_url": documentation_url,  # Add documentation URL
                "version": {
                    "id": version_id,
                    "name": picked.get("name"),
                    "released_at": picked.get("releaseDate"),
                    "release": version_details.get("release", {}),
                    "compatibilities": version_details.get("compatibilities", []),
                    "raw": picked,
                },
                "overview": overview,
                "highlights": highlights,
                "media": media,
                "addon": addon_info,
                "vendor_links": version_details.get("vendorLinks", {}),
            }

            # Create output directory
            output_dir = Path(self.descriptions_dir) / addon_key.replace('.', '_')
            output_dir.mkdir(parents=True, exist_ok=True)

            # Save JSON
            print(f"      Saving JSON file...")
            json_path = output_dir / f"{addon_key.replace('.', '_')}_{payload['version']['name']}.json"
            with json_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            # Save HTML
            print(f"      Saving HTML file...")
            html_path = output_dir / f"{addon_key.replace('.', '_')}_{payload['version']['name']}.html"
            html_path.write_text(self._render_html(payload), encoding="utf-8")

            # Download media if requested
            if download_media:
                print(f"      Downloading media files...")
                self._download_media(media, output_dir / "media")
                print(f"      ✓ Media files downloaded")

            # Download app logo
            print(f"      Downloading app logo...")
            logo_path = self._download_logo(addon_info, output_dir)
            if logo_path:
                print(f"      ✓ Logo downloaded: {logo_path.name}")
            else:
                print(f"      ⚠ Logo not available")

            logger.info(f"Description saved for {addon_key}: {json_path}, {html_path}")
            return json_path, html_path

        except Exception as e:
            logger.error(f"Error downloading description for {addon_key}: {str(e)}")
            return None, None

    def _download_media(self, media: Dict, media_dir: Path):
        """Download media files (screenshots from version details)."""
        if not isinstance(media, dict) or "error" in media:
            return

        screenshots = media.get("screenshots", [])
        if not screenshots:
            return

        media_dir.mkdir(parents=True, exist_ok=True)

        # Use image-appropriate headers (session has Accept: application/json which causes 406)
        image_headers = {
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        for idx, screenshot in enumerate(screenshots):
            if not isinstance(screenshot, dict):
                continue

            # Extract image URL from screenshot structure
            # Structure: _embedded.image._links.image.href or _embedded.image._links.unscaled.href
            embedded_image = (screenshot.get("_embedded") or {}).get("image", {})
            image_links = (embedded_image.get("_links") or {})

            # Prefer unscaled (original), fall back to image
            href = None
            image_type = "image/png"
            for key in ["unscaled", "image", "highRes"]:
                link_data = image_links.get(key, {})
                if isinstance(link_data, dict) and link_data.get("href"):
                    href = link_data["href"]
                    image_type = link_data.get("type", "image/png")
                    break

            if not href:
                continue

            # Extract UUID from URL as filename (e.g., /files/dab3b010-d73d-49b9-9f32-13ab61c45c80 -> dab3b010-d73d-49b9-9f32-13ab61c45c80)
            uuid_match = re.search(r'/files/([a-f0-9-]{36})', href)
            if uuid_match:
                name = uuid_match.group(1)
            else:
                name = f"screenshot_{idx + 1}"

            try:
                # Use requests directly with image headers instead of session
                response = requests.get(href, headers=image_headers, timeout=120)
                response.raise_for_status()

                # Determine extension from actual response content-type
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
                extension = ext_map.get(content_type, ".webp")  # Default to .webp as most images are served as webp

                filename = f"{name}{extension}"
                destination = media_dir / filename
                with destination.open("wb") as f:
                    f.write(response.content)
                logger.debug(f"Downloaded screenshot: {filename}")
            except Exception as e:
                logger.warning(f"Failed to download screenshot {href}: {str(e)}")

    def _download_logo(self, addon_info: Dict, output_dir: Path) -> Optional[Path]:
        """Download app logo from addon info.

        Args:
            addon_info: Addon information from API
            output_dir: Directory to save the logo

        Returns:
            Path to downloaded logo or None if not available
        """
        if not isinstance(addon_info, dict):
            return None

        # Extract logo URL from addon_info._embedded.logo._links.image.href
        # Structure: _embedded.logo._links.image.href or _embedded.logo._links.highDpi.href
        embedded = addon_info.get("_embedded", {})
        logo_data = embedded.get("logo", {})
        logo_links = logo_data.get("_links", {})

        # Try different logo sizes - prefer higher resolution
        href = None
        for key in ["highDpi", "image", "self"]:
            link_data = logo_links.get(key, {})
            if isinstance(link_data, dict) and link_data.get("href"):
                href = link_data["href"]
                break

        if not href:
            # Try alternate path: _links.logo.href -> fetch asset
            logo_link = addon_info.get("_links", {}).get("logo", {}).get("href")
            if logo_link:
                # This is an asset reference like /rest/2/assets/{uuid}
                # Convert to direct image URL
                uuid_match = re.search(r'/assets/([a-f0-9-]{36})', logo_link)
                if uuid_match:
                    uuid = uuid_match.group(1)
                    href = f"https://marketplace.atlassian.com/product-listing/files/{uuid}?width=144&height=144"

        if not href:
            logger.debug("No logo URL found in addon info")
            return None

        # Extract UUID from URL for filename (kept for debugging/logging)
        uuid_match = re.search(r'/files/([a-f0-9-]{36})', href)
        if uuid_match:
            _name = uuid_match.group(1)  # noqa: F841
        else:
            _name = "logo"  # noqa: F841

        # Use image-appropriate headers
        image_headers = {
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        try:
            response = requests.get(href, headers=image_headers, timeout=60)
            response.raise_for_status()

            # Determine extension from content-type
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/svg+xml": ".svg"}
            extension = ext_map.get(content_type, ".webp")

            # Save as logo.{ext} for easy reference
            filename = f"logo{extension}"
            destination = output_dir / filename
            with destination.open("wb") as f:
                f.write(response.content)

            logger.debug(f"Downloaded logo: {filename} ({len(response.content)} bytes)")
            return destination

        except Exception as e:
            logger.warning(f"Failed to download logo {href}: {str(e)}")
            return None

    def download_full_marketplace_page(
        self,
        marketplace_url: Optional[str],
        addon_key: str,
        download_assets: bool = True
    ) -> Optional[Path]:
        """
        Download full HTML page from Marketplace with all assets.

        Args:
            marketplace_url: Full Marketplace URL (can be None)
            addon_key: App key for directory naming
            download_assets: Download all assets (images, videos, CSS, JS)

        Returns:
            Path to saved HTML file or None on error
        """
        try:
            # Validate and fix URL
            if not marketplace_url or not marketplace_url.strip():
                logger.warning(f"Empty marketplace_url for {addon_key}, constructing URL")
                marketplace_url = f"https://marketplace.atlassian.com/apps/{addon_key}?hosting=datacenter&tab=overview"
            else:
                # Ensure URL is absolute
                if marketplace_url.startswith('/'):
                    marketplace_url = f"https://marketplace.atlassian.com{marketplace_url}"
                
                # Add parameters if not present
                from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
                parsed = urlparse(marketplace_url)
                params = parse_qs(parsed.query)
                
                # Ensure hosting parameter
                if 'hosting' not in params:
                    params['hosting'] = ['datacenter']
                
                # Ensure tab parameter for overview
                if 'tab' not in params:
                    params['tab'] = ['overview']
                
                # Reconstruct URL
                query = urlencode(params, doseq=True)
                marketplace_url = urlunparse((
                    parsed.scheme or 'https',
                    parsed.netloc or 'marketplace.atlassian.com',
                    parsed.path,
                    parsed.params,
                    query,
                    parsed.fragment
                ))
            
            # Create output directory
            output_dir = Path(self.descriptions_dir) / addon_key.replace('.', '_') / 'full_page'
            output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Saving full page to: {output_dir}")
            logger.debug(f"Descriptions base dir: {self.descriptions_dir}")
            assets_dir = output_dir / 'assets'
            if download_assets:
                assets_dir.mkdir(exist_ok=True)

            # Download HTML page with proper headers
            logger.info(f"Downloading full page: {marketplace_url}")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            response = self.session.get(marketplace_url, headers=headers, timeout=60, allow_redirects=True)
            
            # Check if we got a 404 or error page
            if response.status_code == 404:
                logger.warning(f"404 error for {marketplace_url}, trying alternative URL")
                # Try alternative URL format
                alt_url = f"https://marketplace.atlassian.com/apps/{addon_key}?hosting=datacenter&tab=overview"
                response = self.session.get(alt_url, headers=headers, timeout=60, allow_redirects=True)
                if response.status_code == 404:
                    logger.error(f"Both URLs returned 404 for {addon_key}")
                    return None
                marketplace_url = alt_url
            
            response.raise_for_status()
            
            # Use response.text which handles decompression automatically
            # But explicitly set encoding to UTF-8
            response.encoding = response.apparent_encoding or 'utf-8'
            if response.encoding.lower() not in ['utf-8', 'utf8']:
                # Force UTF-8 if detected encoding is not UTF-8
                response.encoding = 'utf-8'
            
            html_content = response.text
            
            # Validate that we got valid HTML (not binary data)
            if len(html_content) < 100 or not ('<' in html_content and '>' in html_content):
                logger.warning(f"Response doesn't look like HTML, trying to decode as bytes")
                # Fallback: try to decode raw content
                raw_content = response.content
                try:
                    html_content = raw_content.decode('utf-8', errors='replace')
                except Exception:
                    html_content = raw_content.decode('latin-1', errors='replace')
            
            # Check if we got an error page
            if 'We couldn\'t find the page' in html_content or 'page not found' in html_content.lower():
                logger.warning(f"Got error page for {marketplace_url}, trying alternative URL")
                alt_url = f"https://marketplace.atlassian.com/apps/{addon_key}?hosting=datacenter&tab=overview"
                alt_response = self.session.get(alt_url, headers=headers, timeout=60, allow_redirects=True)
                if alt_response.status_code == 200:
                    # Set encoding for alternative response
                    alt_response.encoding = alt_response.apparent_encoding or 'utf-8'
                    if alt_response.encoding.lower() not in ['utf-8', 'utf8']:
                        alt_response.encoding = 'utf-8'
                    
                    alt_html_content = alt_response.text
                    
                    if 'We couldn\'t find the page' not in alt_html_content:
                        html_content = alt_html_content
                        marketplace_url = alt_url
                    else:
                        logger.error(f"Error page detected for {addon_key}")
                        return None
                else:
                    logger.error(f"Error page detected for {addon_key}")
                    return None

            # Validate HTML content before parsing
            if not html_content or len(html_content) < 100:
                logger.error(f"HTML content is too short or empty: {len(html_content) if html_content else 0} chars")
                raise ValueError("Invalid HTML content: too short")
            
            # Check if content looks like HTML (not binary data)
            if not ('<' in html_content and '>' in html_content):
                logger.error("Content doesn't look like HTML (no tags found)")
                # Try to decode as bytes if it's still binary
                if isinstance(html_content, bytes):
                    try:
                        html_content = html_content.decode('utf-8', errors='replace')
                    except Exception:
                        html_content = html_content.decode('latin-1', errors='replace')
                else:
                    raise ValueError("Content doesn't look like HTML")
            
            # Parse HTML - use lxml parser if available for better encoding handling
            try:
                soup = BeautifulSoup(html_content, 'lxml')
            except Exception as e:
                logger.warning(f"lxml parser failed: {e}, trying html.parser")
                # Fallback to html.parser
                soup = BeautifulSoup(html_content, 'html.parser')

            if download_assets:
                # Find and download all assets
                asset_map = {}  # original_url -> local_path

                # Images
                for img in soup.find_all('img', src=True):
                    src = img['src']
                    if not src.startswith('data:'):
                        local_path = self._download_asset(src, marketplace_url, assets_dir, asset_map)
                        if local_path:
                            # Use relative path from output_dir
                            rel_path = local_path.relative_to(output_dir)
                            img['src'] = str(rel_path).replace('\\', '/')

                # Videos
                for video in soup.find_all('video'):
                    if video.get('src'):
                        src = video['src']
                        local_path = self._download_asset(src, marketplace_url, assets_dir, asset_map)
                        if local_path:
                            rel_path = local_path.relative_to(output_dir)
                            video['src'] = str(rel_path).replace('\\', '/')
                    # Source tags
                    for source in video.find_all('source', src=True):
                        src = source['src']
                        local_path = self._download_asset(src, marketplace_url, assets_dir, asset_map)
                        if local_path:
                            rel_path = local_path.relative_to(output_dir)
                            source['src'] = str(rel_path).replace('\\', '/')

                # CSS files
                for link in soup.find_all('link', rel='stylesheet', href=True):
                    href = link['href']
                    local_path = self._download_asset(href, marketplace_url, assets_dir, asset_map)
                    if local_path:
                        rel_path = local_path.relative_to(output_dir)
                        link['href'] = str(rel_path).replace('\\', '/')

                # JavaScript files
                for script in soup.find_all('script', src=True):
                    src = script['src']
                    local_path = self._download_asset(src, marketplace_url, assets_dir, asset_map)
                    if local_path:
                        rel_path = local_path.relative_to(output_dir)
                        script['src'] = str(rel_path).replace('\\', '/')

                # Background images in style attributes
                for tag in soup.find_all(style=True):
                    style = tag['style']
                    # Find url() in CSS
                    for match in re.finditer(r'url\(["\']?([^"\']+)["\']?\)', style):
                        url = match.group(1)
                        local_path = self._download_asset(url, marketplace_url, assets_dir, asset_map)
                        if local_path:
                            new_url = str(local_path.relative_to(output_dir)).replace('\\', '/')
                            style = style.replace(match.group(0), f'url("{new_url}")')
                    tag['style'] = style

            # Save HTML with proper encoding
            html_path = output_dir / 'index.html'
            
            # Ensure charset meta tag is present
            if soup.head:
                # Check if charset meta tag exists
                charset_tag = soup.head.find('meta', attrs={'charset': True})
                if not charset_tag:
                    charset_tag = soup.new_tag('meta', charset='UTF-8')
                    soup.head.insert(0, charset_tag)
                else:
                    charset_tag['charset'] = 'UTF-8'
            else:
                # Create head if it doesn't exist
                if not soup.find('head'):
                    head = soup.new_tag('head')
                    if soup.html:
                        soup.html.insert(0, head)
                    else:
                        soup.insert(0, head)
                charset_tag = soup.new_tag('meta', charset='UTF-8')
                soup.head.insert(0, charset_tag)
            
            # Save with UTF-8 encoding
            # BeautifulSoup's str() returns a Unicode string
            try:
                # Get string representation from BeautifulSoup
                # Use prettify() for better formatting, but it can be slow for large files
                # So we use str() for speed
                html_str = str(soup)
                
                # Ensure it's a string, not bytes
                if isinstance(html_str, bytes):
                    # If it's bytes, decode it
                    try:
                        html_str = html_str.decode('utf-8', errors='replace')
                    except Exception:
                        html_str = html_str.decode('latin-1', errors='replace')
                
                # Validate HTML content - check if it looks like valid HTML
                if not html_str or len(html_str) < 50:
                    logger.error(f"HTML content is too short or empty: {len(html_str) if html_str else 0} chars")
                    raise ValueError("Invalid HTML content")
                
                # Check for common HTML tags to ensure it's valid HTML
                if '<html' not in html_str.lower() and '<body' not in html_str.lower():
                    logger.warning(f"HTML doesn't contain expected tags, but continuing anyway")
                
                # Ensure DOCTYPE is present (prevents Quirks Mode)
                if not html_str.strip().startswith('<!DOCTYPE'):
                    html_str = '<!DOCTYPE html>\n' + html_str
                
                # Write with explicit UTF-8 encoding using binary mode
                # This ensures proper encoding without any platform-specific issues
                html_bytes = html_str.encode('utf-8', errors='xmlcharrefreplace')
                html_path.write_bytes(html_bytes)
                
                # Verify the file was written correctly
                if not html_path.exists():
                    raise IOError(f"File was not created: {html_path}")
                
                # Verify file size
                file_size = html_path.stat().st_size
                if file_size == 0:
                    raise ValueError(f"File is empty: {html_path}")
                
                logger.debug(f"Saved HTML file: {html_path} ({file_size} bytes)")
                
            except Exception as e:
                logger.error(f"Error writing HTML file {html_path}: {str(e)}")
                # Fallback: try text mode
                try:
                    with html_path.open('w', encoding='utf-8', errors='xmlcharrefreplace', newline='') as f:
                        f.write(html_str)
                    logger.info(f"Fallback text mode write succeeded")
                except Exception as e2:
                    logger.error(f"Fallback write also failed: {str(e2)}")
                    raise

            logger.info(f"Full page saved: {html_path}")
            return html_path

        except Exception as e:
            logger.error(f"Error downloading full page {marketplace_url}: {str(e)}")
            return None

    def _download_asset(
        self,
        url: str,
        base_url: str,
        assets_dir: Path,
        asset_map: Dict[str, Path]
    ) -> Optional[Path]:
        """Download a single asset and return local path."""
        try:
            # Skip data URLs and external domains
            if url.startswith('data:') or url.startswith('javascript:'):
                return None

            # Make absolute URL
            abs_url = urljoin(base_url, url)
            parsed = urlparse(abs_url)

            # Only download from marketplace domain
            if 'marketplace.atlassian.com' not in parsed.netloc:
                return None

            # Check if already downloaded
            if abs_url in asset_map:
                return asset_map[abs_url]

            # Generate filename
            filename = os.path.basename(parsed.path)
            if not filename or '.' not in filename:
                # Use hash for files without extension
                ext = mimetypes.guess_extension(
                    requests.head(abs_url, timeout=10).headers.get('content-type', '')
                ) or '.bin'
                filename = hashlib.md5(abs_url.encode(), usedforsecurity=False).hexdigest()[:16] + ext
            else:
                # Sanitize filename
                filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

            local_path = assets_dir / filename

            # Download if not exists
            if not local_path.exists():
                response = self.session.get(abs_url, timeout=30)
                response.raise_for_status()
                local_path.parent.mkdir(parents=True, exist_ok=True)
                with local_path.open('wb') as f:
                    f.write(response.content)
                logger.debug(f"Downloaded asset: {filename}")

            asset_map[abs_url] = local_path
            return local_path

        except Exception as e:
            logger.debug(f"Failed to download asset {url}: {str(e)}")
            return None

    def download_all_descriptions(self, download_media: bool = True, limit: Optional[int] = None,
                                    use_full_page: bool = True, max_workers: int = 1):
        """
        Download descriptions for all apps in database.

        Args:
            download_media: Download media files
            limit: Optional limit on number of apps to process
            use_full_page: Download full HTML page instead of API-based description
            max_workers: Number of parallel workers (default 1)
        """
        apps = self.store.get_all_apps(limit=limit)
        total = len(apps)

        if max_workers > 1:
            if use_full_page:
                # Use multiprocessing for full-page mode (each process gets its own browser)
                self._download_all_multiprocess(apps, total, download_media, use_full_page, max_workers)
            else:
                # Use threading for API-only mode (no Playwright)
                self._download_all_parallel(apps, total, download_media, use_full_page, max_workers)
        else:
            self._download_all_sequential(apps, total, download_media, use_full_page)

    def _download_all_sequential(self, apps, total, download_media, use_full_page):
        """Sequential download with browser reuse (for full-page mode)."""
        print(f"[*] Starting sequential description download for {total} apps...", flush=True)
        logger.info(f"Starting description download for {total} apps (full_page={use_full_page})")

        success_count = 0
        fail_count = 0
        skip_count = 0

        # Use PlaywrightBrowserManager for browser reuse if downloading full pages
        browser_manager = None
        if use_full_page:
            try:
                from scraper.page_saver_integrated import PlaywrightBrowserManager
                browser_manager = PlaywrightBrowserManager()
                browser_manager.__enter__()
                self._playwright_page = browser_manager.page
                if self._playwright_page:
                    logger.info("Browser reuse enabled - this will be faster")
                else:
                    logger.warning("Browser not available, falling back to new browser per page")
            except ImportError:
                logger.warning("PlaywrightBrowserManager not available")

        try:
            for idx, app in enumerate(apps, 1):
                addon_key = app.get('addon_key')
                if not addon_key:
                    continue

                # Skip if description already exists
                if self.description_exists(addon_key, use_full_page=use_full_page):
                    skip_count += 1
                    print(f"{idx}/{total} [SKIP] {addon_key} (already exists)", flush=True)
                    logger.debug(f"[SKIP] Description already exists: {addon_key}")
                    continue

                # Print progress to stdout for task manager progress bar
                print(f"{idx}/{total} Downloading: {addon_key}", flush=True)
                logger.info(f"[{idx}/{total}] Downloading description for {addon_key}")

                # Get marketplace_url
                marketplace_url = self._get_marketplace_url(app)

                try:
                    json_path, html_path = self.download_description(
                        addon_key,
                        download_media=download_media,
                        marketplace_url=marketplace_url if use_full_page else None
                    )

                    if json_path or html_path:
                        success_count += 1
                        print(f"{idx}/{total} [OK] {addon_key}", flush=True)
                        logger.info(f"[OK] Success: {addon_key}")
                    else:
                        fail_count += 1
                        print(f"{idx}/{total} [FAIL] {addon_key}", flush=True)
                        logger.warning(f"[ERROR] Failed: {addon_key}")
                except KeyboardInterrupt:
                    logger.warning(f"Download interrupted by user at {addon_key}")
                    raise
                except Exception as e:
                    fail_count += 1
                    print(f"{idx}/{total} [ERROR] {addon_key}", flush=True)
                    logger.error(f"[ERROR] Exception downloading {addon_key}: {e}")

        finally:
            self._playwright_page = None
            if browser_manager:
                browser_manager.__exit__(None, None, None)

        print(f"\n[OK] Description download completed successfully! ({success_count} success, {skip_count} skipped, {fail_count} failed)", flush=True)
        logger.info(f"Description download complete: {success_count} success, {skip_count} skipped, {fail_count} failed")

    def _download_all_parallel(self, apps, total, download_media, use_full_page, max_workers):
        """Parallel download for API-only mode (no Playwright)."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from threading import Lock

        print(f"[*] Starting parallel description download for {total} apps ({max_workers} workers)...", flush=True)
        logger.info(f"Starting parallel description download for {total} apps (workers={max_workers})")

        success_count = 0
        fail_count = 0
        skip_count = 0
        completed_count = 0
        lock = Lock()

        def download_single_app(app_info):
            nonlocal success_count, fail_count, skip_count, completed_count

            idx, app = app_info
            addon_key = app.get('addon_key')

            if not addon_key:
                return ('skip', None, None)

            # Skip if description already exists
            if self.description_exists(addon_key, use_full_page=False):
                with lock:
                    completed_count += 1
                    skip_count += 1
                    print(f"{completed_count}/{total} [SKIP] {addon_key} (already exists)", flush=True)
                logger.debug(f"[SKIP] Description already exists: {addon_key}")
                return ('skip', addon_key, None)

            marketplace_url = self._get_marketplace_url(app)

            try:
                json_path, html_path = self.download_description(
                    addon_key,
                    download_media=download_media,
                    marketplace_url=None  # API-only mode
                )

                with lock:
                    completed_count += 1
                    if json_path or html_path:
                        success_count += 1
                        print(f"{completed_count}/{total} [OK] {addon_key}", flush=True)
                        logger.info(f"[OK] Success: {addon_key}")
                        return ('success', addon_key, html_path)
                    else:
                        fail_count += 1
                        print(f"{completed_count}/{total} [FAIL] {addon_key}", flush=True)
                        logger.warning(f"[ERROR] Failed: {addon_key}")
                        return ('fail', addon_key, None)

            except Exception as e:
                with lock:
                    completed_count += 1
                    fail_count += 1
                    print(f"{completed_count}/{total} [ERROR] {addon_key}", flush=True)
                logger.error(f"[ERROR] Exception downloading {addon_key}: {e}")
                return ('error', addon_key, str(e))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(download_single_app, (idx, app)): app
                      for idx, app in enumerate(apps, 1)}

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Worker exception: {e}")

        print(f"\n[OK] Description download completed successfully! ({success_count} success, {skip_count} skipped, {fail_count} failed)", flush=True)
        logger.info(f"Description download complete: {success_count} success, {skip_count} skipped, {fail_count} failed")

    def _get_marketplace_url(self, app):
        """Extract marketplace URL from app dict."""
        marketplace_url_raw = app.get('marketplace_url')
        marketplace_url = None
        if marketplace_url_raw:
            if isinstance(marketplace_url_raw, dict):
                marketplace_url = marketplace_url_raw.get('href', '')
            elif isinstance(marketplace_url_raw, str):
                marketplace_url = marketplace_url_raw.strip()

        if not marketplace_url:
            addon_key = app.get('addon_key', '')
            marketplace_url = f"https://marketplace.atlassian.com/apps/{addon_key}?hosting=datacenter&tab=overview"

        return marketplace_url

    def _download_all_multiprocess(self, apps, total, download_media, use_full_page, max_workers):
        """Parallel download using multiprocessing (each process gets its own browser)."""
        import signal
        from multiprocessing import Pool, Manager

        print(f"[*] Starting multiprocess description download for {total} apps ({max_workers} workers)...", flush=True)
        print(f"[*] Each worker process will have its own browser instance", flush=True)
        logger.info(f"Starting multiprocess description download for {total} apps (workers={max_workers})")

        # Prepare work items with all needed data
        work_items = []
        for idx, app in enumerate(apps, 1):
            addon_key = app.get('addon_key')
            if not addon_key:
                continue
            marketplace_url = self._get_marketplace_url(app)
            work_items.append({
                'idx': idx,
                'total': total,
                'addon_key': addon_key,
                'marketplace_url': marketplace_url,
                'download_media': download_media,
                'use_full_page': use_full_page,
                'descriptions_dir': self.descriptions_dir
            })

        # Track pool for signal handling
        pool = None
        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)

        def signal_handler(signum, frame):
            """Handle termination signals by cleaning up the pool."""
            logger.warning(f"Received signal {signum}, terminating worker processes...")
            print(f"\n[!] Received termination signal, stopping workers...", flush=True)
            if pool is not None:
                pool.terminate()
                pool.join()
            # Re-raise to allow proper cleanup
            raise KeyboardInterrupt("Task cancelled")

        try:
            # Set up signal handlers
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)

            # Process in batches - each worker processes multiple items with browser reuse
            batch_size = max(1, len(work_items) // max_workers)
            batches = [work_items[i:i + batch_size] for i in range(0, len(work_items), batch_size)]

            # Limit to max_workers batches
            if len(batches) > max_workers:
                # Redistribute items to exactly max_workers batches
                batches = [[] for _ in range(max_workers)]
                for i, item in enumerate(work_items):
                    batches[i % max_workers].append(item)

            pool = Pool(processes=max_workers)
            try:
                results = pool.map(_worker_process_batch, batches)
            finally:
                pool.close()
                pool.join()
                pool = None

            # Aggregate results
            success_count = sum(r['success'] for r in results)
            fail_count = sum(r['fail'] for r in results)
            skip_count = sum(r.get('skip', 0) for r in results)

            print(f"\n[OK] Description download completed successfully! ({success_count} success, {skip_count} skipped, {fail_count} failed)", flush=True)
            logger.info(f"Description download complete: {success_count} success, {skip_count} skipped, {fail_count} failed")

        except KeyboardInterrupt:
            print(f"\n[!] Download cancelled by user", flush=True)
            logger.warning("Download cancelled by user")
            raise
        finally:
            # Restore original signal handlers
            signal.signal(signal.SIGTERM, original_sigterm)
            signal.signal(signal.SIGINT, original_sigint)
            # Ensure pool is terminated
            if pool is not None:
                pool.terminate()
                pool.join()

    def save_marketplace_page_with_playwright(
        self,
        download_url: str,
        save_path: Union[str, os.PathLike],
        format: str = "mhtml",
        wait_seconds: int = 8,
        timeout: int = 90,
    ) -> Path:
        """
        Save Marketplace page using Playwright (headless browser).
        This method executes JavaScript and captures the fully rendered page.
        
        Args:
            download_url: Marketplace URL (can be relative or absolute)
            save_path: Where to save the file
            format: Output format - "mhtml" (single file) or "html" (HTML + assets folder)
            wait_seconds: How long to wait after page load for JS to finish
            timeout: Maximum time to wait for page load
            
        Returns:
            Path to saved file
            
        Raises:
            ImportError: If playwright is not installed
            Exception: If page save fails
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
        except ImportError:
            raise ImportError(
                "playwright is required for this method. Install it with: pip install playwright && playwright install chromium"
            )
        
        page_url = _normalize_marketplace_url(str(download_url).strip())
        save_path = Path(save_path).expanduser().resolve()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Saving page with Playwright: {page_url} -> {save_path}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox'
                ]
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                bypass_csp=True,
                # Ignore HTTPS errors if needed
                ignore_https_errors=False
            )
            
            # Block unnecessary resources to speed up loading
            def route_handler(route):
                url = route.request.url
                # Block analytics, tracking, and other non-essential resources
                blocked_patterns = [
                    'analytics', 'tracking', 'doubleclick', 'googlesyndication',
                    'facebook.com/tr', 'optimizely.com', 'hotjar.com',
                    'googletagmanager.com', 'google-analytics.com'
                ]
                if any(pattern in url.lower() for pattern in blocked_patterns):
                    route.abort()
                else:
                    route.continue_()
            
            context.route("**/*", route_handler)
            
            # Add authentication if available
            if settings.MARKETPLACE_USERNAME and settings.MARKETPLACE_API_TOKEN:
                import base64
                token = base64.b64encode(
                    f"{settings.MARKETPLACE_USERNAME}:{settings.MARKETPLACE_API_TOKEN}".encode("utf-8")
                ).decode("ascii")
                context.set_extra_http_headers({
                    "Authorization": f"Basic {token}"
                })
            
            page = context.new_page()
            
            try:
                # Navigate and wait for page to load
                # Use "load" instead of "networkidle" as Marketplace has continuous background requests
                # Marketplace pages never reach "networkidle" due to analytics/tracking
                try:
                    page.goto(page_url, wait_until="load", timeout=timeout * 1000)
                    logger.debug("Page loaded successfully")
                except Exception as e:
                    # If load fails, try domcontentloaded as fallback
                    logger.warning(f"Load timeout ({timeout}s), trying domcontentloaded: {str(e)[:100]}")
                    try:
                        page.goto(page_url, wait_until="domcontentloaded", timeout=timeout * 1000)
                        logger.debug("Page loaded with domcontentloaded")
                    except Exception as e2:
                        # Last resort: just navigate without waiting
                        logger.warning(f"domcontentloaded also failed, proceeding anyway: {str(e2)[:100]}")
                        page.goto(page_url, timeout=30000)  # 30 second minimum
                
                # Wait additional time for JavaScript to finish rendering
                # This gives time for SPA to render content
                logger.debug(f"Waiting {wait_seconds} seconds for JavaScript to render...")
                page.wait_for_timeout(wait_seconds * 1000)
                
                # Try to wait for specific elements that indicate page is loaded
                # This is more reliable than networkidle for SPAs
                content_loaded = False
                selectors_to_try = [
                    "main",
                    "[role='main']",
                    "#amkt-frontend-content",
                    "section",
                    "article",
                    ".app-details",
                    "[data-testid]"
                ]
                
                for selector in selectors_to_try:
                    try:
                        page.wait_for_selector(selector, timeout=5000)
                        logger.debug(f"Content selector found: {selector}")
                        content_loaded = True
                        break
                    except PlaywrightTimeout:
                        continue  # Selector not found, try next
                
                if not content_loaded:
                    logger.warning("No content selectors found, but proceeding anyway")
                
                # Additional wait to ensure all dynamic content is loaded
                # Marketplace SPA may need extra time to render
                page.wait_for_timeout(3000)  # 3 more seconds
                
                # Check if page has actual content (not just skeleton/loading)
                try:
                    page_text = page.inner_text("body")
                    text_length = len(page_text)
                    logger.debug(f"Page text length: {text_length} characters")
                    if text_length < 100:
                        logger.warning(f"Page content seems too short ({text_length} chars), waiting more...")
                        page.wait_for_timeout(5000)  # Wait 5 more seconds
                        # Check again
                        page_text = page.inner_text("body")
                        text_length = len(page_text)
                        logger.debug(f"Page text length after additional wait: {text_length} characters")
                except Exception as e:
                    logger.debug(f"Could not check page text length: {str(e)}")
                
                if format.lower() == "mhtml":
                    # Save as MHTML (single file, includes all resources)
                    # Use CDP (Chrome DevTools Protocol) to capture snapshot
                    try:
                        cdp = context.new_cdp_session(page)
                        result = cdp.send("Page.captureSnapshot", {"format": "mhtml"})
                        mhtml_data = result.get("data", "")
                        
                        if not mhtml_data or len(mhtml_data) < 1000:
                            # If MHTML is too small, fallback to HTML method
                            logger.warning("MHTML data seems empty or too small, using HTML method instead")
                            raise ValueError("MHTML data too small")
                        
                        save_path.write_text(mhtml_data, encoding="utf-8", errors="replace")
                        file_size = save_path.stat().st_size
                        logger.info(f"Saved MHTML: {save_path} ({file_size} bytes)")
                        
                        # Verify file was written correctly
                        if file_size < 1000:
                            raise ValueError(f"MHTML file too small: {file_size} bytes")
                            
                    except Exception as e:
                        # Fallback: save as HTML with embedded resources
                        logger.warning(f"MHTML capture failed: {str(e)}, falling back to HTML method")
                        html_content = page.content()
                        
                        # Remove scripts to prevent SPA routing issues
                        soup = BeautifulSoup(html_content, "lxml")
                        for s in soup.find_all("script"):
                            s.decompose()
                        
                        # Ensure metadata
                        self._ensure_html_metadata(soup)
                        
                        # Save as HTML instead
                        html_path = save_path.with_suffix('.html')
                        out_html = str(soup)
                        if not out_html.strip().startswith('<!DOCTYPE'):
                            out_html = '<!DOCTYPE html>\n' + out_html
                        html_path.write_text(out_html, encoding="utf-8", errors="replace")
                        logger.info(f"Saved as HTML instead: {html_path} ({html_path.stat().st_size} bytes)")
                        return html_path
                    
                elif format.lower() == "html":
                    # Save as HTML with assets folder - using full page_saver logic
                    # Get page content after JS execution
                    html_content = page.content()
                    final_url = page.url
                    
                    # Check if HTML has content
                    if not html_content or len(html_content) < 1000:
                        logger.error("HTML content is empty or too small, page may not have loaded")
                        raise ValueError("Page content is empty")
                    
                    # Parse HTML
                    soup = BeautifulSoup(html_content, "lxml")
                    
                    # Create assets directory
                    assets_dir = save_path.parent / "assets"
                    assets_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Dictionary to track downloaded assets: abs_url -> rel_path
                    downloaded_assets: Dict[str, str] = {}
                    
                    # Helper to save asset and return relative path
                    def save_asset(abs_url: str, subfolder: str = "") -> str:
                        """Download asset and return relative path from HTML to asset."""
                        if _should_skip_resource(abs_url):
                            return abs_url
                        if abs_url in downloaded_assets:
                            return downloaded_assets[abs_url]
                        
                        try:
                            resp = self.session.get(abs_url, timeout=timeout)
                            resp.raise_for_status()
                        except Exception as e:
                            logger.debug(f"Failed to download asset {abs_url}: {e}")
                            return abs_url
                        
                        # Determine file extension from content-type or URL
                        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                        _default_ext = {  # noqa: F841 - dict used inline for .get()
                            "text/css": ".css",
                            "application/javascript": ".js",
                            "text/javascript": ".js",
                            "image/png": ".png",
                            "image/jpeg": ".jpg",
                            "image/jpg": ".jpg",
                            "image/gif": ".gif",
                            "image/webp": ".webp",
                            "image/svg+xml": ".svg",
                            "font/woff2": ".woff2",
                            "font/woff": ".woff",
                            "font/ttf": ".ttf",
                        }.get(ctype, "")
                        
                        fname = _safe_filename_from_url(abs_url, ctype)
                        
                        # Determine target directory
                        if subfolder:
                            target_dir = assets_dir / subfolder
                        else:
                            target_dir = assets_dir
                        target_dir.mkdir(parents=True, exist_ok=True)
                        
                        target = target_dir / fname
                        
                        # Write file
                        target.write_bytes(resp.content)
                        logger.debug(f"Downloaded asset: {abs_url} -> {target.name}")
                        
                        # Calculate relative path from HTML to asset
                        try:
                            rel_path = os.path.relpath(target, save_path.parent)
                            rel_path = rel_path.replace("\\", "/")
                            if not rel_path.startswith(("./", "../", "assets/")):
                                rel_path = "assets/" + rel_path.split("assets/")[-1] if "assets/" in rel_path else "assets/" + fname
                        except (ValueError, OSError):
                            # Fallback for different drives
                            rel_path = f"assets/{subfolder}/{fname}" if subfolder else f"assets/{fname}"
                        
                        downloaded_assets[abs_url] = rel_path
                        return rel_path
                    
                    # Process images
                    for img in soup.find_all("img"):
                        if img.has_attr("src"):
                            src = img["src"]
                            if not _should_skip_resource(src):
                                abs_src = urljoin(final_url, src)
                                img["src"] = save_asset(abs_src, "img")
                    
                    # Process stylesheets and icons
                    for link in soup.find_all("link"):
                        href = link.get("href")
                        if not href or _should_skip_resource(href):
                            continue
                        rel = ",".join(link.get("rel", [])).lower()
                        if "stylesheet" in rel or ("preload" in rel and link.get("as") == "style"):
                            abs_href = urljoin(final_url, href)
                            link["href"] = save_asset(abs_href, "css")
                        elif any(k in rel for k in ["icon", "shortcut icon", "apple-touch-icon"]):
                            abs_href = urljoin(final_url, href)
                            link["href"] = save_asset(abs_href, "icons")
                    
                    # Process scripts
                    for script in soup.find_all("script"):
                        src = script.get("src")
                        if src and not _should_skip_resource(src):
                            abs_src = urljoin(final_url, src)
                            script["src"] = save_asset(abs_src, "js")
                    
                    # Process media (video, audio)
                    for tag_name, attr in [("video", "src"), ("video", "poster"), ("audio", "src"), ("source", "src")]:
                        for tag in soup.find_all(tag_name):
                            if tag.has_attr(attr):
                                src = tag[attr]
                                if not _should_skip_resource(src):
                                    abs_src = urljoin(final_url, src)
                                    tag[attr] = save_asset(abs_src, "media")
                    
                    # Process CSS files - rewrite url() inside CSS
                    _CSS_URL_RE = re.compile(r"url\(\s*([\"']?)(.+?)\1\s*\)", re.IGNORECASE)
                    for link in soup.find_all("link", rel=lambda x: x and "stylesheet" in " ".join(x).lower()):
                        href = link.get("href")
                        if href and not _should_skip_resource(href):
                            # Find the local CSS file path
                            css_rel = link["href"]
                            if css_rel.startswith("assets/"):
                                css_path = save_path.parent / css_rel
                                if css_path.exists():
                                    try:
                                        css_text = css_path.read_text(encoding="utf-8", errors="ignore")
                                        # Find all url() in CSS
                                        for match in _CSS_URL_RE.finditer(css_text):
                                            url_in_css = match.group(2).strip()
                                            if not _should_skip_resource(url_in_css):
                                                abs_css_url = urljoin(final_url, url_in_css)
                                                local_css_asset = save_asset(abs_css_url, "css_assets")
                                                css_text = css_text.replace(url_in_css, local_css_asset)
                                        css_path.write_text(css_text, encoding="utf-8")
                                    except Exception as e:
                                        logger.debug(f"Failed to process CSS file {css_path}: {e}")
                    
                    # Inject offline patches at the beginning of <head>
                    head = soup.find("head")
                    if not head:
                        head = soup.new_tag("head")
                        soup.html.insert(0, head)
                    
                    patch_script = soup.new_tag("script")
                    patch_script.string = """
                    (function() {
                        'use strict';
                        // Block fetch for API calls
                        if (typeof fetch !== 'undefined') {
                            const originalFetch = window.fetch;
                            window.fetch = function(...args) {
                                const url = args[0] && typeof args[0] === 'string' ? args[0] : 
                                            (args[0] && args[0].url ? args[0].url : '');
                                // Allow local files
                                if (url && (
                                    url.startsWith('file://') ||
                                    url.startsWith('./') ||
                                    url.startsWith('../') ||
                                    (!url.includes('://') && !url.startsWith('/') && !url.startsWith('http'))
                                )) {
                                    return originalFetch.apply(this, args);
                                }
                                // Block API calls
                                if (url && (
                                    url.includes('api.atlassian.com') ||
                                    url.includes('gateway/') ||
                                    url.includes('/api/') ||
                                    url.startsWith('http://') ||
                                    url.startsWith('https://')
                                )) {
                                    console.log('[Offline Mode] Blocked fetch:', url);
                                    return Promise.reject(new Error('Offline mode: API call blocked'));
                                }
                                return originalFetch.apply(this, args);
                            };
                        }
                        // Block XMLHttpRequest for API calls
                        if (typeof XMLHttpRequest !== 'undefined') {
                            const OriginalXHR = window.XMLHttpRequest;
                            window.XMLHttpRequest = function() {
                                const xhr = new OriginalXHR();
                                const originalOpen = xhr.open;
                                xhr.open = function(method, url, ...rest) {
                                    if (url && (
                                        url.startsWith('file://') ||
                                        url.startsWith('./') ||
                                        url.startsWith('../') ||
                                        (!url.includes('://') && !url.startsWith('/') && !url.startsWith('http'))
                                    )) {
                                        return originalOpen.apply(this, [method, url, ...rest]);
                                    }
                                    if (url && (
                                        url.includes('api.atlassian.com') ||
                                        url.includes('gateway/') ||
                                        url.includes('/api/') ||
                                        url.startsWith('http://') ||
                                        url.startsWith('https://')
                                    )) {
                                        console.log('[Offline Mode] Blocked XHR:', url);
                                        xhr.readyState = 0;
                                        return;
                                    }
                                    return originalOpen.apply(this, [method, url, ...rest]);
                                };
                                return xhr;
                            };
                        }
                    })();
                    """
                    head.insert(0, patch_script)
                    
                    # Remove all remaining script tags (except the patch)
                    for script in soup.find_all("script"):
                        if script != patch_script:
                            script.decompose()
                    
                    # Remove base tag if exists (for offline mode)
                    for base in soup.find_all("base"):
                        base.decompose()
                    
                    # Ensure DOCTYPE and metadata
                    self._ensure_html_metadata(soup)
                    
                    # Save final HTML
                    out_html = str(soup)
                    if not out_html.strip().startswith('<!DOCTYPE'):
                        out_html = '<!DOCTYPE html>\n' + out_html
                    
                    save_path.write_text(out_html, encoding="utf-8", errors="replace")
                    file_size = save_path.stat().st_size
                    logger.info(f"Saved HTML with assets: {save_path} ({file_size} bytes, {len(downloaded_assets)} assets in {assets_dir})")
                    
                    if file_size < 1000:
                        raise ValueError(f"HTML file too small: {file_size} bytes")
                    
                else:
                    raise ValueError(f"Unsupported format: {format}. Use 'mhtml' or 'html'")
                    
            finally:
                context.close()
                browser.close()
        
        return save_path

    def save_marketplace_plugin_page(
        self,
        download_url: str,
        save_html_path: Union[str, os.PathLike],
        encoding: str = "utf-8",
        download_media: bool = False,
        timeout: int = 30,
    ) -> Tuple[Path, Optional[Path]]:
        """
        Save Marketplace page so it can be opened locally (file://).
        - Removes all <script> tags (so SPA doesn't redraw page as 404)
        - Optionally downloads CSS + images and rewrites links to local files

        This is the RECOMMENDED method for offline viewing as it preserves
        the visual content of the page without SPA JavaScript dependencies.

        Args:
            download_url: Link from JSON (href can be relative "/apps/...")
            save_html_path: Where to save HTML
            encoding: Encoding to write HTML to disk
            download_media: Download CSS/images and rewrite links to local
            timeout: Request timeout in seconds

        Returns:
            Tuple of (path_to_html, path_to_assets_dir_or_None)
        """
        if not download_url or not str(download_url).strip():
            raise ValueError("download_url is empty")

        page_url = _normalize_marketplace_url(str(download_url).strip())

        html_path = Path(save_html_path).expanduser().resolve()
        html_path.parent.mkdir(parents=True, exist_ok=True)

        # Use existing session (already has auth if configured)
        session = self.session
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (offline-snapshot; requests)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

        resp = session.get(page_url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()

        # Ensure UTF-8 encoding for response
        if resp.encoding is None or resp.encoding.lower() not in ['utf-8', 'utf8']:
            resp.encoding = 'utf-8'

        # Decode original HTML
        html_text = resp.content.decode(encoding, errors="replace")

        soup = BeautifulSoup(html_text, "lxml")

        # KEY: Remove ALL scripts FIRST (otherwise SPA on file:// will show 404)
        # This must be done before any other processing to prevent scripts from being re-added
        scripts_removed = 0
        for s in soup.find_all("script"):
            s.decompose()
            scripts_removed += 1
        logger.debug(f"Removed {scripts_removed} script tags to prevent SPA routing")
        
        # Also remove noscript tags that might contain scripts or cause issues
        for ns in soup.find_all("noscript"):
            ns.decompose()

        # If media not needed - just save "sanitized" HTML
        if not download_media:
            self._rewrite_links_to_absolute_marketplace(soup, base_url=resp.url)
            # Ensure charset and DOCTYPE
            self._ensure_html_metadata(soup)
            out_html = str(soup)
            if not out_html.strip().startswith('<!DOCTYPE'):
                out_html = '<!DOCTYPE html>\n' + out_html
            html_path.write_bytes(out_html.encode(encoding, errors="replace"))
            logger.info(f"Saved HTML page (no media): {html_path}")
            return html_path, None

        # If need to "download media" - create assets folder
        assets_dir = html_path.parent / f"{html_path.stem}_assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        # Download and rewrite:
        # - <link rel="stylesheet" href="...">
        # - <img src="...">
        # - <link rel="icon"...> (optional)
        # + inside CSS download url(...) (fonts/images)
        # NOTE: Scripts are NOT downloaded - they were already removed above
        self._download_and_rewrite_assets(session, soup, base_url=resp.url, assets_dir=assets_dir, timeout=timeout)

        # IMPORTANT: Remove any scripts that might have been added during asset processing
        # (shouldn't happen, but just in case)
        for s in soup.find_all("script"):
            s.decompose()

        # To make links to other Marketplace pages work normally - rewrite relative href/src to absolute
        self._rewrite_links_to_absolute_marketplace(soup, base_url=resp.url, keep_local_assets_dir=assets_dir.name)

        # Ensure charset and DOCTYPE
        self._ensure_html_metadata(soup)

        # Convert to string and ensure DOCTYPE
        out_html = str(soup)
        if not out_html.strip().startswith('<!DOCTYPE'):
            out_html = '<!DOCTYPE html>\n' + out_html

        # Final check: ensure no scripts remain in the output
        if '<script' in out_html.lower():
            logger.warning(f"WARNING: Scripts still present in HTML after processing! Attempting to remove...")
            # Use regex as last resort
            import re
            out_html = re.sub(r'<script\b[^>]*>.*?</script[^>]*>', '', out_html, flags=re.DOTALL | re.IGNORECASE)
            out_html = re.sub(r'<noscript\b[^>]*>.*?</noscript[^>]*>', '', out_html, flags=re.DOTALL | re.IGNORECASE)

        html_path.write_bytes(out_html.encode(encoding, errors="replace"))
        logger.info(f"Saved HTML page with media assets: {html_path}")
        return html_path, assets_dir

    def _download_resource_simple(
        self, session: requests.Session, abs_url: str, assets_dir: Path, timeout: int = 30
    ) -> str:
        """
        Download a single resource and return relative path.

        Args:
            session: Requests session
            abs_url: Absolute URL of resource
            assets_dir: Directory to save assets
            timeout: Request timeout

        Returns:
            Relative path from HTML: "<assets_dir_name>/<file>"
        """
        r = session.get(abs_url, timeout=timeout, stream=True, allow_redirects=True)
        r.raise_for_status()

        content_type = r.headers.get("Content-Type")
        filename = _safe_filename_from_url(abs_url, content_type)
        out_path = assets_dir / filename

        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)

        # Return relative path from HTML: "<assets_dir_name>/<file>"
        return f"{assets_dir.name}/{filename}"

    def _is_local_asset_path(self, value: str, local_dir_name: str) -> bool:
        """
        Check if path is a local asset path.

        Args:
            value: Path to check
            local_dir_name: Name of local assets directory

        Returns:
            True if path is local asset
        """
        v = (value or "").strip()
        return v.startswith(f"{local_dir_name}/") or v.startswith(f"./{local_dir_name}/")

    def _rewrite_links_to_absolute_marketplace(
        self, soup: BeautifulSoup, base_url: str, keep_local_assets_dir: Optional[str] = None
    ) -> None:
        """
        Rewrite links so that:
        - Relative links to marketplace become absolute (https://marketplace...)
        - But local assets (assets_dir/...) are not touched

        Args:
            soup: BeautifulSoup object
            base_url: Base URL for resolving relative links
            keep_local_assets_dir: Name of local assets directory to preserve
        """
        attrs = [("a", "href"), ("img", "src"), ("link", "href"), ("source", "src")]

        for tag_name, attr in attrs:
            for tag in soup.find_all(tag_name):
                val = tag.get(attr)
                if not val:
                    continue
                val = str(val).strip()

                if keep_local_assets_dir and self._is_local_asset_path(val, keep_local_assets_dir):
                    continue

                if val.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
                    continue

                if val.startswith("//"):
                    tag[attr] = "https:" + val
                    continue

                if val.startswith("/"):
                    tag[attr] = urljoin(MARKETPLACE_BASE, val)
                    continue

                # Relative to current page
                if not val.lower().startswith(("http://", "https://")):
                    tag[attr] = urljoin(base_url, val)

    def _download_and_rewrite_assets(
        self, session: requests.Session, soup: BeautifulSoup, base_url: str, assets_dir: Path, timeout: int
    ) -> None:
        """
        Download and rewrite CSS and images.
        NOTE: Scripts are NOT downloaded - they are removed to prevent SPA routing issues.

        Args:
            session: Requests session
            soup: BeautifulSoup object
            base_url: Base URL for resolving relative links
            assets_dir: Directory to save assets
            timeout: Request timeout
        """
        # IMPORTANT: Do NOT download scripts - they are already removed and should stay removed
        
        # --- CSS ---
        for link in soup.find_all("link"):
            rel = link.get("rel") or []
            rel_str = " ".join([r.lower() for r in rel]) if isinstance(rel, list) else str(rel).lower()

            href = link.get("href")
            if not href:
                continue

            href = str(href).strip()
            if href.startswith(("data:", "javascript:")):
                continue

            is_css = "stylesheet" in rel_str
            is_icon = ("icon" in rel_str) or ("shortcut icon" in rel_str)

            if not (is_css or is_icon):
                continue

            abs_url = urljoin(base_url, href)
            try:
                content, content_type = self._http_get_bytes(session, abs_url, timeout)
            except Exception as e:
                logger.debug(f"Failed to download {abs_url}: {str(e)}")
                continue

            # Save
            local_name = _safe_filename_from_url(abs_url, content_type)
            local_path = assets_dir / local_name
            local_path.write_bytes(content)

            # If it's CSS - rewrite url(...) inside and download resources
            if is_css:
                try:
                    css_text = content.decode("utf-8", errors="replace")
                    css_text = self._localize_css_urls(
                        session, css_text, css_base_url=abs_url, assets_dir=assets_dir, timeout=timeout
                    )
                    local_path.write_text(css_text, encoding="utf-8", errors="replace")
                except Exception as e:
                    logger.debug(f"Failed to process CSS {abs_url}: {str(e)}")

            # Rewrite link
            link["href"] = f"{assets_dir.name}/{local_name}"

        # --- IMG ---
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue
            src = str(src).strip()

            if src.startswith(("data:", "javascript:")):
                continue

            abs_url = urljoin(base_url, src)
            try:
                content, content_type = self._http_get_bytes(session, abs_url, timeout)
            except Exception as e:
                logger.debug(f"Failed to download image {abs_url}: {str(e)}")
                continue

            local_name = _safe_filename_from_url(abs_url, content_type)
            (assets_dir / local_name).write_bytes(content)

            img["src"] = f"{assets_dir.name}/{local_name}"

    def _localize_css_urls(
        self, session: requests.Session, css_text: str, css_base_url: str, assets_dir: Path, timeout: int
    ) -> str:
        """
        Inside CSS find url(...) and download corresponding resources (fonts/images),
        rewriting them to local paths.

        Args:
            session: Requests session
            css_text: CSS content
            css_base_url: Base URL for CSS file (for resolving relative URLs)
            assets_dir: Directory to save assets
            timeout: Request timeout

        Returns:
            CSS text with rewritten URLs
        """
        # url('...') / url("...") / url(...)
        pattern = re.compile(r"url\(\s*(['\"]?)([^'\"\)]+)\1\s*\)", re.IGNORECASE)

        def repl(m: re.Match) -> str:
            raw = m.group(2).strip()
            if raw.startswith(("data:", "javascript:", "#")):
                return m.group(0)

            abs_url = urljoin(css_base_url, raw)
            try:
                content, content_type = self._http_get_bytes(session, abs_url, timeout)
            except Exception:
                return m.group(0)

            local_name = _safe_filename_from_url(abs_url, content_type)
            (assets_dir / local_name).write_bytes(content)
            return f"url('{assets_dir.name}/{local_name}')"

        return pattern.sub(repl, css_text)

    def _http_get_bytes(self, session: requests.Session, url: str, timeout: int) -> Tuple[bytes, str]:
        """
        Get bytes and content type from URL.

        Args:
            session: Requests session
            url: URL to fetch
            timeout: Request timeout

        Returns:
            Tuple of (content_bytes, content_type)
        """
        r = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        return r.content, content_type

    def _ensure_html_metadata(self, soup: BeautifulSoup) -> None:
        """
        Ensure HTML has charset meta tag and DOCTYPE.

        Args:
            soup: BeautifulSoup object
        """
        # Ensure charset meta tag
        if soup.head:
            charset_tag = soup.head.find('meta', attrs={'charset': True})
            if not charset_tag:
                charset_tag = soup.new_tag('meta', charset='UTF-8')
                soup.head.insert(0, charset_tag)
            else:
                charset_tag['charset'] = 'UTF-8'
        else:
            if not soup.find('head'):
                head = soup.new_tag('head')
                if soup.html:
                    soup.html.insert(0, head)
                else:
                    soup.insert(0, head)
            charset_tag = soup.new_tag('meta', charset='UTF-8')
            soup.head.insert(0, charset_tag)

        # DOCTYPE will be added when converting to string

    def save_marketplace_plugin_page_static(
        self,
        download_url: str,
        save_html_path: Union[str, os.PathLike],
        encoding: str = "utf-8",
        download_media: bool = False,
        addon_key: Optional[str] = None,
        timeout: int = 30,
    ) -> Tuple[Path, Optional[Path]]:
        """
        Create a static HTML snapshot of plugin page using Marketplace REST API.
        This generates a standalone HTML file that works offline (file://) without SPA dependencies.

        This is the recommended method for offline viewing, as it doesn't rely on
        Marketplace's JavaScript SPA which fails when opened via file:// protocol.

        Args:
            download_url: Link from JSON (href can be relative "/apps/...")
            save_html_path: Where to save HTML
            encoding: Encoding to write HTML to disk
            download_media: Download images (logo and description images) locally
            addon_key: Addon key (if not provided, will try to extract from HTML)
            timeout: Request timeout in seconds

        Returns:
            Tuple of (path_to_html, path_to_assets_dir_or_None)
        """
        page_url = _normalize_marketplace_url(str(download_url).strip())
        html_path = Path(save_html_path).expanduser().resolve()
        html_path.parent.mkdir(parents=True, exist_ok=True)

        # Use existing session (already has auth if configured)
        session = self.session
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (offline-static-snapshot)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

        # 1) If addon_key not provided, try to extract from HTML page
        if not addon_key:
            page_resp = session.get(page_url, timeout=timeout, allow_redirects=True)
            page_resp.raise_for_status()
            # Ensure UTF-8 encoding
            if page_resp.encoding is None or page_resp.encoding.lower() not in ['utf-8', 'utf8']:
                page_resp.encoding = 'utf-8'
            page_html = page_resp.text
            addon_key = self._extract_addon_key_from_marketplace_html(page_html)

        if not addon_key:
            raise ValueError(
                "Could not determine addon_key from HTML. "
                "Please provide addon_key explicitly (from JSON field 'addon_key')."
            )

        # 2) Fetch data via Marketplace REST API
        api_url = f"{API_BASE}/addons/{addon_key}"
        api_resp = session.get(
            api_url,
            timeout=timeout,
            allow_redirects=True,
            headers={"Accept": "application/json"}
        )
        api_resp.raise_for_status()
        # Ensure UTF-8 encoding
        if api_resp.encoding is None or api_resp.encoding.lower() not in ['utf-8', 'utf8']:
            api_resp.encoding = 'utf-8'
        data = api_resp.json()

        # 3) Prepare assets
        assets_dir: Optional[Path] = None
        if download_media:
            assets_dir = html_path.parent / f"{html_path.stem}_assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

        # 4) Extract fields (API structure may vary - do safely)
        name = self._deep_get(data, ["name"]) or addon_key
        summary = self._deep_get(data, ["summary"]) or self._deep_get(data, ["tagline"]) or ""
        vendor_name = (
            self._deep_get(data, ["vendor", "name"])
            or self._deep_get(data, ["vendor", "company", "name"])
            or ""
        )
        homepage = self._deep_get(data, ["vendor", "links", "homepage"]) or ""

        # Description in API is often stored as HTML (or as "description"/"text")
        description_html = (
            self._deep_get(data, ["description"])
            or self._deep_get(data, ["details", "description"])
            or self._deep_get(data, ["text"])
            or ""
        )

        # Sometimes description comes as plain text, not HTML - escape carefully
        if description_html and ("<" not in description_html and ">" not in description_html):
            description_html = "<p>" + escape(description_html).replace("\n", "<br>") + "</p>"

        # Logo: in API it can be in different places. Try several variants.
        logo_url = (
            self._deep_get(data, ["_links", "logo", "href"])
            or self._deep_get(data, ["_links", "icon", "href"])
            or self._deep_get(data, ["logo", "href"])
            or ""
        )
        if logo_url:
            logo_url = urljoin(MARKETPLACE_BASE, logo_url)

        # 5) If downloading media: logo + images from description
        local_logo_rel = ""
        if download_media and assets_dir and logo_url:
            try:
                local_logo_rel = self._download_binary_static(session, logo_url, assets_dir, timeout)
            except Exception as e:
                logger.warning(f"Failed to download logo {logo_url}: {str(e)}")
                local_logo_rel = logo_url  # Fallback to original URL

        if download_media and assets_dir and description_html:
            description_html = self._localize_images_in_html(session, description_html, assets_dir, timeout)

        # 6) Build final static HTML
        final_html = self._render_static_html(
            name=name,
            addon_key=addon_key,
            vendor=vendor_name,
            summary=summary,
            homepage=homepage,
            source_url=page_url,
            logo_rel=local_logo_rel if local_logo_rel else logo_url,
            description_html=description_html,
        )

        html_path.write_bytes(final_html.encode(encoding, errors="replace"))
        logger.info(f"Saved static HTML snapshot: {html_path}")
        return html_path, assets_dir

    def _extract_addon_key_from_marketplace_html(self, page_html: str) -> Optional[str]:
        """
        Try to extract addonKey from HTML. This is heuristic.
        If you already have addon_key in JSON, it's better to pass it explicitly.

        Args:
            page_html: HTML content of marketplace page

        Returns:
            Addon key or None if not found
        """
        if not page_html:
            return None

        # Common key patterns in JSON within page
        patterns = [
            r'"addonKey"\s*:\s*"([^"]+)"',
            r'"addon_key"\s*:\s*"([^"]+)"',
            r'"appKey"\s*:\s*"([^"]+)"',
            r'"pluginKey"\s*:\s*"([^"]+)"',
        ]
        for p in patterns:
            m = re.search(p, page_html)
            if m:
                return m.group(1)

        # Sometimes appears as "addon-com.xxx"
        m = re.search(r'addon-([a-zA-Z0-9_.-]+)', page_html)
        if m:
            return m.group(1)

        return None
    
    def _extract_documentation_url_from_html(self, page_html: str) -> Optional[str]:
        """
        Extract vendor documentation URL from HTML page Resources section.
        Looks for "App documentation" link in Resources block.

        Args:
            page_html: HTML content of marketplace page

        Returns:
            Documentation URL or None if not found
        """
        if not page_html:
            return None
        
        try:
            soup = BeautifulSoup(page_html, 'html.parser')
            
            # Method 1: Look for Resources section with "App documentation"
            # Find section with "Resources" heading
            resources_section = None
            for heading in soup.find_all(['h2', 'h3', 'h4', 'h5', 'h6']):
                if heading.get_text().strip().lower() == 'resources':
                    # Find parent section
                    resources_section = heading.find_parent(['section', 'div', 'article'])
                    break
            
            if resources_section:
                # Look for "App documentation" text and find associated link
                for elem in resources_section.find_all(['a', 'div', 'span', 'p']):
                    text = elem.get_text().strip().lower()
                    # Check if it contains "app documentation" or "documentation"
                    if 'app documentation' in text or ('documentation' in text and 'comprehensive' in text):
                        # Find link in this element or nearby
                        link = elem.find('a', href=True)
                        if link:
                            href = link.get('href', '')
                            if href:
                                # Make absolute URL if relative
                                if href.startswith('/'):
                                    return f"{MARKETPLACE_BASE}{href}"
                                elif href.startswith('http'):
                                    return href
                                else:
                                    return f"{MARKETPLACE_BASE}/{href.lstrip('/')}"
                        
                        # Check if the element itself is a link
                        if elem.name == 'a' and elem.get('href'):
                            href = elem.get('href')
                            if href:
                                if href.startswith('/'):
                                    return f"{MARKETPLACE_BASE}{href}"
                                elif href.startswith('http'):
                                    return href
                                else:
                                    return f"{MARKETPLACE_BASE}/{href.lstrip('/')}"
            
            # Method 2: Search for links with "documentation" in text or near "comprehensive"
            for link in soup.find_all('a', href=True):
                text = link.get_text().strip().lower()
                parent_text = ''
                if link.parent:
                    parent_text = link.parent.get_text().strip().lower()
                
                # Look for "how this app works" or "comprehensive" near documentation
                if ('documentation' in text or 'documentation' in parent_text) and \
                   ('comprehensive' in text or 'comprehensive' in parent_text or 'how this app works' in text or 'how this app works' in parent_text):
                    href = link.get('href', '')
                    if href:
                        if href.startswith('/'):
                            return f"{MARKETPLACE_BASE}{href}"
                        elif href.startswith('http'):
                            return href
                        else:
                            return f"{MARKETPLACE_BASE}/{href.lstrip('/')}"
            
            # Method 3: Regex search for common patterns
            # Look for links in Resources section using regex
            resources_pattern = r'(?i)resources.*?app\s+documentation.*?href=["\']([^"\']+)["\']'
            match = re.search(resources_pattern, page_html, re.DOTALL)
            if match:
                href = match.group(1)
                if href:
                    if href.startswith('/'):
                        return f"{MARKETPLACE_BASE}{href}"
                    elif href.startswith('http'):
                        return href
                    else:
                        return f"{MARKETPLACE_BASE}/{href.lstrip('/')}"
            
        except Exception as e:
            logger.warning(f"Error extracting documentation URL from HTML: {str(e)}")
        
        return None

    def _deep_get(self, obj: Dict, path: List[str]) -> Optional[str]:
        """
        Safely get nested dictionary value.

        Args:
            obj: Dictionary to search
            path: List of keys to traverse

        Returns:
            Value or None if not found
        """
        cur = obj
        for key in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
            if cur is None:
                return None
        return cur

    def _download_binary_static(self, session: requests.Session, url: str, assets_dir: Path, timeout: int) -> str:
        """
        Download binary file and return relative path.

        Args:
            session: Requests session
            url: URL to download
            assets_dir: Directory to save file
            timeout: Request timeout

        Returns:
            Relative path from HTML: "<assets_dir_name>/<file>"
        """
        r = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
        r.raise_for_status()

        # Filename from URL tail
        name = re.sub(r"[^a-zA-Z0-9._-]", "_", url.split("?")[0].split("/")[-1] or "asset")
        out = assets_dir / name

        with open(out, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)

        return f"{assets_dir.name}/{out.name}"

    def _localize_images_in_html(
        self, session: requests.Session, html_fragment: str, assets_dir: Path, timeout: int
    ) -> str:
        """
        Find images in HTML and download them, rewriting src to local paths.

        Args:
            session: Requests session
            html_fragment: HTML content with images
            assets_dir: Directory to save images
            timeout: Request timeout

        Returns:
            HTML with rewritten image src attributes
        """
        soup = BeautifulSoup(html_fragment, "lxml")

        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue

            src = src.strip()
            if src.startswith("data:"):
                continue

            abs_url = urljoin(MARKETPLACE_BASE, src) if src.startswith("/") else src
            try:
                rel = self._download_binary_static(session, abs_url, assets_dir, timeout)
                img["src"] = rel.replace("\\", "/")
            except Exception as e:
                # If download failed, leave as is
                logger.debug(f"Failed to download image {abs_url}: {str(e)}")
                pass

        return str(soup)

    def _render_static_html(
        self,
        name: str,
        addon_key: str,
        vendor: str,
        summary: str,
        homepage: str,
        source_url: str,
        logo_rel: str,
        description_html: str,
    ) -> str:
        """
        Render static HTML template for plugin page.

        Args:
            name: Plugin name
            addon_key: Addon key
            vendor: Vendor name
            summary: Plugin summary
            homepage: Vendor homepage URL
            source_url: Original marketplace URL
            logo_rel: Logo relative path or URL
            description_html: HTML description content

        Returns:
            Complete HTML document as string
        """
        vendor_line = (
            f"<div class='meta'><b>Vendor:</b> {escape(vendor)}</div>" if vendor else ""
        )
        homepage_line = (
            f"<div class='meta'><b>Vendor site:</b> <a href='{escape(homepage)}' target='_blank'>{escape(homepage)}</a></div>"
            if homepage else ""
        )
        logo_block = (
            f"<img class='logo' src='{escape(logo_rel)}' alt='logo'>" if logo_rel else ""
        )

        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(name)} — Marketplace snapshot</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #172B4D; background: #F4F5F7; }}
    .card {{ max-width: 1100px; margin: 0 auto; background: white; padding: 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    .header {{ display:flex; gap:16px; align-items:center; margin-bottom: 24px; }}
    .logo {{ width:72px; height:72px; object-fit:contain; border-radius:12px; border:1px solid #DFE1E6; background:#fff; padding: 4px; }}
    h1 {{ margin: 0; font-size: 26px; color: #172B4D; }}
    .sub {{ margin-top: 6px; color:#42526E; font-size: 14px; }}
    .meta {{ margin-top: 6px; color:#42526E; font-size: 13px; }}
    .src {{ margin-top: 10px; font-size: 13px; color:#6B778C; }}
    .desc {{ margin-top: 18px; padding-top: 16px; border-top:1px solid #DFE1E6; }}
    .desc img {{ max-width: 100%; height: auto; border-radius: 4px; }}
    a {{ color:#0C66E4; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    code {{ background:#F4F5F7; padding:2px 6px; border-radius:4px; font-size: 12px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      {logo_block}
      <div>
        <h1>{escape(name)}</h1>
        <div class="sub">{escape(summary)}</div>
        <div class="meta"><b>Addon key:</b> <code>{escape(addon_key)}</code></div>
        {vendor_line}
        {homepage_line}
        <div class="src">Source: <a href="{escape(source_url)}" target="_blank">{escape(source_url)}</a></div>
      </div>
    </div>

    <div class="desc">
      {description_html or "<i>Description not available in API data</i>"}
    </div>
  </div>
</body>
</html>
"""

