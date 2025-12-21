"""Download plugin descriptions with images and videos from Atlassian Marketplace."""

import os
import json
import re
import hashlib
import mimetypes
from pathlib import Path
from typing import Dict, Optional, Tuple, List
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

    def _fetch(self, url: str, params: Optional[Dict] = None) -> Dict:
        """Fetch data from API."""
        try:
            response = self.session.get(url, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"value": data}
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            raise

    def _fetch_with_fallback(
        self,
        primary_url: str,
        fallback_url: Optional[str] = None,
        params: Optional[Dict] = None
    ) -> Dict:
        """Fetch with fallback URL."""
        try:
            return self._fetch(primary_url, params=params)
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
                    return self._fetch(candidate_url, params=candidate_params)
                except HTTPError:
                    continue

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
        overview_body = overview.get("body") or overview.get("content")
        description_html = overview_body or legacy_description or "<p>Description not available.</p>"

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
        vendor_logo = (
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
        if isinstance(highlights, dict) and "error" not in highlights:
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
            items = media.get("_embedded", {}).get("media", []) or []
            media_links = []
            for idx, item in enumerate(items, start=1):
                binaries = item.get("_embedded", {}).get("binary", []) or []
                for binary in binaries:
                    href = binary.get("href")
                    if not href:
                        continue
                    name = binary.get("name") or binary.get("type") or f"media-{idx}"
                    media_links.append(f'<li><a href="{escape(href)}" target="_blank" rel="noopener">{escape(name)}</a></li>')
            if media_links:
                media_items_html = "<ul class=\"link-list\">" + "\n".join(media_links) + "</ul>"
            else:
                media_items_html = '<p class="muted">Media links not found.</p>'
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
        marketplace_url: Optional[str] = None
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
        # If marketplace_url provided, download full page instead
        if marketplace_url:
            html_path = self.download_full_marketplace_page(
                marketplace_url,
                addon_key,
                download_assets=download_media
            )
            if html_path:
                return None, html_path
            # Fallback to API if full page download fails
            logger.warning(f"Full page download failed, falling back to API for {addon_key}")
        try:
            # Get versions
            versions = self._get_versions(addon_key, hosting)
            if not versions:
                logger.warning(f"No versions found for {addon_key}")
                return None, None

            picked = self._pick_version(versions, version_name)
            if not picked:
                logger.warning(f"Version '{version_name}' not found for {addon_key}")
                return None, None

            version_id = picked.get("id")
            if not version_id:
                self_href = ((picked.get("_links") or {}).get("self") or {}).get("href", "")
                if isinstance(self_href, str) and self_href:
                    match = re.search(r"/versions/(?:build/)?(\d+)", self_href)
                    if match:
                        version_id = match.group(1)

            if not version_id:
                logger.error(f"Version ID not found for {addon_key}")
                return None, None

            params = {"locale": locale}

            overview_url = f"{API_BASE}/addons/{addon_key}/versions/{version_id}/overview"
            highlights_url = f"{API_BASE}/addons/{addon_key}/versions/{version_id}/highlights"
            media_url = f"{API_BASE}/addons/{addon_key}/versions/{version_id}/media"
            addon_url = f"{API_BASE}/addons/{addon_key}"

            overview = self._fetch_with_fallback(
                overview_url,
                fallback_url=f"{API_BASE}/addons/{addon_key}/overview",
                params=params
            )
            highlights = self._fetch_with_fallback(
                highlights_url,
                fallback_url=f"{API_BASE}/addons/{addon_key}/highlights",
                params=params
            )
            media = self._fetch_with_fallback(
                media_url,
                fallback_url=f"{API_BASE}/addons/{addon_key}/media",
                params=params
            )
            addon_info = self._fetch(addon_url, params={"locale": locale, "hosting": hosting, "expand": "details"})

            payload = {
                "addon_key": addon_key,
                "hosting": hosting,
                "locale": locale,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "version": {
                    "id": version_id,
                    "name": picked.get("name"),
                    "released_at": picked.get("releaseDate"),
                    "raw": picked,
                },
                "overview": overview,
                "highlights": highlights,
                "media": media,
                "addon": addon_info,
            }

            # Create output directory
            output_dir = Path(self.descriptions_dir) / addon_key.replace('.', '_')
            output_dir.mkdir(parents=True, exist_ok=True)

            # Save JSON
            json_path = output_dir / f"{addon_key.replace('.', '_')}_{payload['version']['name']}.json"
            with json_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            # Save HTML
            html_path = output_dir / f"{addon_key.replace('.', '_')}_{payload['version']['name']}.html"
            html_path.write_text(self._render_html(payload), encoding="utf-8")

            # Download media if requested
            if download_media:
                self._download_media(media, output_dir / "media")

            logger.info(f"Description saved for {addon_key}: {json_path}, {html_path}")
            return json_path, html_path

        except Exception as e:
            logger.error(f"Error downloading description for {addon_key}: {str(e)}")
            return None, None

    def _download_media(self, media: Dict, media_dir: Path):
        """Download media files (images/videos)."""
        if not isinstance(media, dict) or "error" in media:
            return

        media_items = (media.get("_embedded") or {}).get("media", []) or []
        if not media_items:
            return

        media_dir.mkdir(parents=True, exist_ok=True)
        for item in media_items:
            assets = item.get("_embedded", {}).get("binary", []) if isinstance(item, dict) else []
            for asset in assets:
                href = asset.get("href")
                name = asset.get("name") or asset.get("type") or "media"
                if not href:
                    continue
                try:
                    response = self.session.get(href, timeout=120)
                    response.raise_for_status()
                    extension = Path(href).suffix or ".bin"
                    filename = f"{name}{extension}"
                    # Sanitize filename
                    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                    destination = media_dir / filename
                    with destination.open("wb") as f:
                        f.write(response.content)
                    logger.debug(f"Downloaded media: {filename}")
                except Exception as e:
                    logger.warning(f"Failed to download media {href}: {str(e)}")

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
                filename = hashlib.md5(abs_url.encode()).hexdigest()[:16] + ext
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

    def download_all_descriptions(self, download_media: bool = True, limit: Optional[int] = None, use_full_page: bool = True):
        """
        Download descriptions for all apps in database.

        Args:
            download_media: Download media files
            limit: Optional limit on number of apps to process
            use_full_page: Download full HTML page instead of API-based description
        """
        apps = self.store.get_all_apps(limit=limit)
        total = len(apps)
        logger.info(f"Starting description download for {total} apps (full_page={use_full_page})")

        success_count = 0
        fail_count = 0

        for idx, app in enumerate(apps, 1):
            addon_key = app.get('addon_key')
            marketplace_url = app.get('marketplace_url')
            
            if not addon_key:
                continue

            logger.info(f"[{idx}/{total}] Downloading description for {addon_key}")

            # If marketplace_url is empty, try to construct it
            if not marketplace_url or not marketplace_url.strip():
                logger.debug(f"marketplace_url is empty for {addon_key}, will construct URL")
                marketplace_url = None  # Will be constructed in download_full_marketplace_page

            if use_full_page:
                # Download full HTML page
                html_path = self.download_full_marketplace_page(
                    marketplace_url,
                    addon_key,
                    download_assets=download_media
                )
                if html_path:
                    success_count += 1
                    logger.info(f"[OK] Success: {addon_key}")
                else:
                    fail_count += 1
                    logger.warning(f"[ERROR] Failed: {addon_key}")
            else:
                # Use API-based description
                json_path, html_path = self.download_description(
                    addon_key,
                    download_media=download_media
                )

                if json_path and html_path:
                    success_count += 1
                    logger.info(f"[OK] Success: {addon_key}")
                else:
                    fail_count += 1
                    logger.warning(f"[ERROR] Failed: {addon_key}")

        logger.info(f"Description download complete: {success_count} success, {fail_count} failed")

