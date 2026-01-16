# -*- coding: utf-8 -*-
"""
Integrated web page saver module.
Full version with Playwright support and resource downloading.
"""

from __future__ import annotations

import os
import re
import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup
from utils.logger import get_logger

logger = get_logger('description_downloader')

__all__ = ["save_webpage_full", "SaveResult", "PlaywrightBrowserManager"]


@dataclass
class SaveResult:
    """Page save result."""
    output_html: str           # path to saved HTML
    assets_dir: Optional[str]  # assets folder (None in online mode)
    mode: str                  # "OFFLINE" or "ONLINE"


# ------------------------ helper functions ------------------------

def _user_agent() -> str:
    return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36")


def _sanitize_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = name.split("?")[0].split("#")[0]
    return name or "file"


def _ensure_ext_by_mime(path: Path, content_type: str) -> Path:
    if not content_type:
        return path
    guess = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
    if guess and path.suffix.lower() != guess.lower():
        return path.with_suffix(guess)
    return path


def _hashed_name(url: str, fallback_ext: str = "") -> str:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    ext = ""
    base = os.path.basename(url.split("?")[0].split("#")[0])
    if "." in base:
        ext = "." + base.split(".")[-1]
    elif fallback_ext:
        ext = fallback_ext
    return f"{h}{ext}"


def _is_data_url(u: str) -> bool:
    return u.strip().startswith("data:")


def _get_full_resolution_url(url: str) -> str:
    """
    Convert image URL to full resolution by removing/modifying size parameters.

    Handles common CDN patterns:
    - ?width=300&height=160 -> remove these params
    - /w_300,h_160/ (Cloudinary) -> remove or increase
    - ?w=300&h=160 -> remove these params
    """
    if not url or _is_data_url(url):
        return url

    try:
        parsed = urlparse(url)

        # Parse query parameters
        params = parse_qs(parsed.query, keep_blank_values=True)

        # Remove common size-limiting parameters
        size_params = ['width', 'height', 'w', 'h', 'size', 'resize',
                       'maxwidth', 'maxheight', 'max-width', 'max-height',
                       'fit', 'crop', 'thumbnail']
        modified = False
        for param in size_params:
            if param in params:
                del params[param]
                modified = True

        if modified:
            # Rebuild the URL without size parameters
            new_query = urlencode(params, doseq=True) if params else ''
            new_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment
            ))
            return new_url

        return url
    except Exception:
        return url


# CSS url() processing
_CSS_URL_RE = re.compile(r"url\(\s*([\"']?)(.+?)\1\s*\)", re.IGNORECASE)


def _find_css_urls(css_text: str):
    for m in _CSS_URL_RE.finditer(css_text or ""):
        url = m.group(2).strip()
        if url and not url.startswith("about:"):
            yield url


def _rewrite_css_urls(css_text: str, repl_map: Dict[str, str]) -> str:
    def _sub(m):
        quote = m.group(1) or ""
        url = m.group(2).strip()
        new = repl_map.get(url, url)
        return f"url({quote}{new}{quote})"
    return _CSS_URL_RE.sub(_sub, css_text or "")


# ------------------------------ core -------------------------------------

class _Saver:
    def __init__(self, url: str, out_html: Path, assets_dir: Optional[Path], offline: bool, timeout: int, session: Optional[requests.Session] = None, playwright_page=None):
        self.url = url
        self.out_html = out_html
        self.assets_dir = assets_dir
        self.offline = offline
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": _user_agent()})
        self._downloaded: Dict[str, str] = {}  # abs_url -> rel_path/from html
        self._playwright_resources: List[str] = []  # Resources found via Playwright
        self._playwright_page = playwright_page  # Reusable Playwright page (optional)

    def _abs_url(self, base: str, maybe: str) -> str:
        if not maybe:
            return ""
        if _is_data_url(maybe):
            return maybe
        return urljoin(base, maybe)

    def _save_asset(self, abs_url: str, subfolder: str = "") -> str:
        """Downloads resource and returns relative path for HTML/CSS."""
        if _is_data_url(abs_url):
            return abs_url
        if abs_url in self._downloaded:
            return self._downloaded[abs_url]

        # Check if this is an image URL that needs special headers
        # product-listing/files/ URLs require browser-like Accept headers
        is_image_url = (
            'product-listing/files/' in abs_url or
            subfolder == 'img' or
            any(abs_url.lower().endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'))
        )

        try:
            if is_image_url:
                # Use image-appropriate headers (session may have Accept: application/json)
                image_headers = {
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                }
                resp = requests.get(abs_url, headers=image_headers, timeout=self.timeout)
            else:
                resp = self.session.get(abs_url, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as e:
            logger.debug(f"Failed to download resource {abs_url}: {e}")
            return abs_url

        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        default_ext = {
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

        fname = _hashed_name(abs_url, fallback_ext=default_ext)

        if self.assets_dir:
            if subfolder:
                target_dir = Path(self.assets_dir) / subfolder
            else:
                target_dir = Path(self.assets_dir)
        else:
            target_dir = self.out_html.parent

        target_dir.mkdir(parents=True, exist_ok=True)

        target = target_dir / _sanitize_filename(fname)
        target = _ensure_ext_by_mime(target, ctype)

        target.write_bytes(resp.content)
        logger.debug(f"Downloaded resource: {abs_url} -> {target.name}")

        try:
            rel_path = os.path.relpath(target, self.out_html.parent)
            if os.path.isabs(rel_path):
                html_dir_parts = Path(self.out_html.parent).parts
                target_parts = Path(target).parts
                common_len = 0
                for i, (h_part, t_part) in enumerate(zip(html_dir_parts, target_parts)):
                    if h_part.lower() == t_part.lower():
                        common_len = i + 1
                    else:
                        break
                up_levels = len(html_dir_parts) - common_len
                down_parts = target_parts[common_len:]
                rel_path = ("../" * up_levels) + "/".join(down_parts)
        except (ValueError, OSError):
            if self.assets_dir:
                try:
                    assets_path = Path(self.assets_dir).resolve()
                    target_resolved = target.resolve()
                    try:
                        rel_path = os.path.relpath(target_resolved, assets_path)
                        if not rel_path.startswith("."):
                            rel_path = "assets/" + rel_path.replace("\\", "/")
                    except ValueError:
                        rel_path = "assets/" + target.name
                except Exception:
                    rel_path = "assets/" + target.name
            else:
                rel_path = "assets/" + target.name
        
        rel_path = rel_path.replace("\\", "/")
        while "//" in rel_path:
            rel_path = rel_path.replace("//", "/")
        while "/./" in rel_path:
            rel_path = rel_path.replace("/./", "/")
        
        if not rel_path.startswith(("http://", "https://", "/", "./", "../")):
            rel_path = "./" + rel_path
        
        logger.debug(f"Relative path to resource: {rel_path} (from {abs_url})")
        
        self._downloaded[abs_url] = rel_path
        return rel_path

    def _handle_src_like(self, base_url: str, value: str, kind: str = "") -> str:
        abs_u = self._abs_url(base_url, value)
        if not abs_u:
            return value

        # For images, try to get full resolution by removing size parameters
        if kind == "img":
            abs_u = _get_full_resolution_url(abs_u)

        if not self.offline:
            return abs_u
        sub = {"img": "img", "media": "media"}.get(kind, "assets")
        return self._save_asset(abs_u, subfolder=sub)

    def _process_srcset(self, base_url: str, srcset_value: str) -> str:
        """Process srcset, keeping only the largest image for offline use."""
        if not srcset_value:
            return ""

        parts = []
        max_width = 0
        best_url = None

        for item in srcset_value.split(","):
            item = item.strip()
            if not item:
                continue
            tokens = item.split()
            url_part = tokens[0]
            desc = " ".join(tokens[1:]) if len(tokens) > 1 else ""

            # Parse width descriptor (e.g., "300w")
            width = 0
            for d in desc.split():
                if d.endswith('w'):
                    try:
                        width = int(d[:-1])
                    except ValueError:
                        pass  # Invalid width descriptor, skip it

            new_url = self._handle_src_like(base_url, url_part, kind="img")
            parts.append((new_url, desc))

            # Track the largest image
            if width > max_width:
                max_width = width
                best_url = new_url

        # For offline mode, return only the largest image to save space
        if self.offline and best_url:
            return best_url

        return ", ".join((" ".join([u, d]).strip() for u, d in parts))

    def _inject_base_tag(self, soup: BeautifulSoup, base_url: str):
        head = soup.find("head")
        if not head:
            head = soup.new_tag("head")
            soup.html.insert(0, head)

        for b in head.find_all("base"):
            b.decompose()

        if self.offline:
            # In offline mode, we don't inject a <base> tag since all URLs are
            # rewritten to local relative paths. Adding a <base> tag would break
            # these local references by making them resolve against the original URL.
            pass
        else:
            base = soup.new_tag("base", href=base_url)
            head.insert(0, base)

    def _inject_offline_patches(self, soup: BeautifulSoup):
        """Injects patches to block API calls at the beginning of the page."""
        head = soup.find("head")
        if not head:
            head = soup.new_tag("head")
            if soup.html:
                soup.html.insert(0, head)
            else:
                return
        
        patch_script = soup.new_tag("script")
        patch_script.string = """
        (function() {
            'use strict';
            // Disable React hydration to prevent 404 errors when viewing offline
            // The React app checks URL against its routes; our Flask URLs don't match
            if (typeof window !== 'undefined') {
                var _initialState = null;
                Object.defineProperty(window, '__INITIAL_STATE__', {
                    get: function() { return _initialState; },
                    set: function(value) {
                        // Intercept and disable hydration when __INITIAL_STATE__ is set
                        if (value && value.initialConfig) {
                            value.initialConfig.shouldHydrate = false;
                        }
                        _initialState = value;
                    },
                    configurable: true
                });
                // Mark that hydration is disabled
                Object.defineProperty(window, '__HYDRATION_DISABLED__', { value: true, writable: false });
            }
            if (typeof fetch !== 'undefined') {
                const originalFetch = window.fetch;
                window.fetch = function(...args) {
                    const url = args[0] && typeof args[0] === 'string' ? args[0] : 
                                (args[0] && args[0].url ? args[0].url : '');
                    if (url && (
                        url.startsWith('file://') ||
                        url.startsWith('./') ||
                        url.startsWith('../') ||
                        (!url.includes('://') && !url.startsWith('/') && !url.startsWith('Z:/') && !url.startsWith('/Z:/'))
                    )) {
                        return originalFetch.apply(this, args);
                    }
                    // Allow YouTube, Google Video, and related media domains
                    if (url && (
                        url.includes('youtube.com') ||
                        url.includes('youtu.be') ||
                        url.includes('ytimg.com') ||
                        url.includes('googlevideo.com') ||
                        url.includes('ggpht.com')
                    )) {
                        return originalFetch.apply(this, args);
                    }
                    if (url && (
                        url.includes('api.atlassian.com') ||
                        url.includes('marketplace.atlassian.com') ||
                        url.includes('gateway/') ||
                        url.includes('/api/') ||
                        url.includes('/rest/') ||
                        url.includes('px.ads.linkedin.com') ||
                        url.includes('facebook.com/tr') ||
                        url.includes('xp.atlassian.com') ||
                        url.includes('analytics') ||
                        url.includes('segment.io') ||
                        url.startsWith('http://') ||
                        url.startsWith('https://') ||
                        url.startsWith('/Z:/') ||
                        url.startsWith('Z:/')
                    )) {
                        console.log('[Offline Mode] Blocked fetch:', url);
                        return Promise.reject(new Error('Offline mode: API call blocked'));
                    }
                    return originalFetch.apply(this, args);
                };
            }
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
                            (!url.includes('://') && !url.startsWith('/') && !url.startsWith('Z:/') && !url.startsWith('/Z:/'))
                        )) {
                            return originalOpen.apply(this, [method, url, ...rest]);
                        }
                        // Allow YouTube, Google Video, and related media domains
                        if (url && (
                            url.includes('youtube.com') ||
                            url.includes('youtu.be') ||
                            url.includes('ytimg.com') ||
                            url.includes('googlevideo.com') ||
                            url.includes('ggpht.com')
                        )) {
                            return originalOpen.apply(this, [method, url, ...rest]);
                        }
                        if (url && (
                            url.includes('api.atlassian.com') ||
                            url.includes('marketplace.atlassian.com') ||
                            url.includes('gateway/') ||
                            url.includes('/api/') ||
                            url.includes('/rest/') ||
                            url.includes('px.ads.linkedin.com') ||
                            url.includes('facebook.com') ||
                            url.includes('xp.atlassian.com') ||
                            url.includes('analytics') ||
                            url.startsWith('http://') ||
                            url.startsWith('https://') ||
                            url.startsWith('/Z:/') ||
                            url.startsWith('Z:/')
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
            if (typeof window !== 'undefined' && window.addEventListener) {
                // Block all errors related to resource loading
                var originalConsoleError = console.error;
                console.error = function() {
                    var args = Array.prototype.slice.call(arguments);
                    var message = args.join(' ');
                    // Suppress errors related to file://, CORS, and missing files
                    if (message.includes('file://') || 
                        message.includes('CORS') || 
                        message.includes('ERR_FILE_NOT_FOUND') ||
                        message.includes('ERR_FAILED') ||
                        message.includes('ERR_CONNECTION_RESET') ||
                        message.includes('ERR_NAME_NOT_RESOLVED') ||
                        message.includes('amkt-frontend') ||
                        message.includes('gateway') ||
                        message.includes('globalRequire') ||
                        message.includes('onetrust') ||
                        message.includes('statsig') ||
                        message.includes('optimizely')) {
                        // Suppress these errors
                        return;
                    }
                    // For other errors use original console.error
                    originalConsoleError.apply(console, args);
                };
                
                window.addEventListener('error', function(e) {
                    var errorMsg = (e.message || '').toString();
                    var errorSrc = (e.filename || e.source || '').toString();
                    
                    // Suppress errors related to file://, CORS, missing files
                    if (errorMsg.includes('ChunkLoadError') ||
                        errorMsg.includes('Failed to fetch') ||
                        errorMsg.includes('net::ERR') ||
                        errorMsg.includes('API call blocked') ||
                        errorMsg.includes('Offline mode') ||
                        errorMsg.includes('CORS') ||
                        errorMsg.includes('file://') ||
                        errorMsg.includes('globalRequire') ||
                        errorMsg.includes('Cannot read properties') ||
                        errorSrc.includes('amkt-frontend') ||
                        errorSrc.includes('gateway') ||
                        errorSrc.includes('/I:/') ||
                        errorSrc.includes('/Z:/')) {
                        e.preventDefault();
                        e.stopPropagation();
                        e.stopImmediatePropagation();
                        return false;
                    }
                }, true);
                
                // Block API error messages
                window.addEventListener('unhandledrejection', function(e) {
                    var reason = e.reason || {};
                    var reasonMsg = (reason.message || reason.toString() || '').toString();
                    
                    if (reasonMsg.includes('Offline mode') ||
                        reasonMsg.includes('API call blocked') ||
                        reasonMsg.includes('CORS') ||
                        reasonMsg.includes('Failed to fetch') ||
                        reasonMsg.includes('net::ERR')) {
                        e.preventDefault();
                        e.stopPropagation();
                        return false;
                    }
                }, true);
            }
            
            // Hide API error elements after loading
            if (typeof document !== 'undefined' && document.addEventListener) {
                // Run immediately, don't wait for DOMContentLoaded
                function initOfflineMode() {
                    // Hide API error messages
                    var errorElements = document.querySelectorAll('[class*="error"], [class*="outage"], [id*="error"], [id*="outage"]');
                    errorElements.forEach(function(el) {
                        var text = el.textContent || el.innerText || '';
                        if (text.includes('outage') || text.includes('experiencing') || text.includes('error')) {
                            el.style.display = 'none';
                        }
                    });

                    // Activate YouTube player (yt-lite) in offline mode
                    activateYouTubePlayers();

                    // Activate tabs in offline mode
                    activateOfflineTabs();

                    // Activate image lightbox
                    activateImageLightbox();
                }

                // YouTube player activation for yt-lite components
                function activateYouTubePlayers() {
                    // Find all yt-lite containers
                    var ytContainers = document.querySelectorAll('[class*="yt-lite"], [data-youtube], [data-videoid]');
                    console.log('[Offline Mode] Found ' + ytContainers.length + ' YouTube containers');

                    ytContainers.forEach(function(container) {
                        // Get video ID from various possible sources
                        var videoId = container.getAttribute('data-videoid') ||
                                     container.getAttribute('data-youtube') ||
                                     container.getAttribute('data-id');

                        // Try to extract from background-image URL if not found
                        if (!videoId) {
                            var bgImage = window.getComputedStyle(container).backgroundImage ||
                                         container.style.backgroundImage || '';
                            var match = bgImage.match(/vi\/([a-zA-Z0-9_-]+)\//);
                            if (match) videoId = match[1];
                        }

                        if (!videoId) {
                            console.log('[Offline Mode] No video ID found for container');
                            return;
                        }

                        console.log('[Offline Mode] Setting up YouTube player for video: ' + videoId);

                        // Add play button if not present
                        var playBtn = container.querySelector('[class*="playbtn"], [class*="play-btn"], button');
                        if (!playBtn) {
                            playBtn = document.createElement('div');
                            playBtn.innerHTML = '▶';
                            playBtn.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);' +
                                'width:68px;height:48px;background:#f00;border-radius:14px;cursor:pointer;' +
                                'display:flex;align-items:center;justify-content:center;font-size:24px;color:#fff;';
                            container.style.position = 'relative';
                            container.appendChild(playBtn);
                        }

                        // Set up thumbnail background if not present
                        if (!container.style.backgroundImage && !window.getComputedStyle(container).backgroundImage.includes('ytimg')) {
                            container.style.backgroundImage = 'url(https://i.ytimg.com/vi/' + videoId + '/hqdefault.jpg)';
                            container.style.backgroundSize = 'cover';
                            container.style.backgroundPosition = 'center';
                        }

                        // Add click handler to load iframe
                        container.style.cursor = 'pointer';
                        container.addEventListener('click', function(e) {
                            e.preventDefault();
                            e.stopPropagation();

                            console.log('[Offline Mode] Playing YouTube video: ' + videoId);

                            // Create YouTube iframe
                            var iframe = document.createElement('iframe');
                            iframe.src = 'https://www.youtube.com/embed/' + videoId + '?autoplay=1&rel=0';
                            iframe.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;border:none;';
                            iframe.setAttribute('allowfullscreen', '');
                            iframe.setAttribute('allow', 'autoplay; encrypted-media');

                            // Replace container content with iframe
                            container.innerHTML = '';
                            container.style.position = 'relative';
                            container.appendChild(iframe);
                        }, { once: true });
                    });
                }

                // Image lightbox activation
                function activateImageLightbox() {
                    var images = document.querySelectorAll('img[data-src], img[src*="product-listing"], [class*="screenshot"] img, [class*="gallery"] img');
                    console.log('[Offline Mode] Found ' + images.length + ' lightbox images');

                    images.forEach(function(img) {
                        if (img.closest('[class*="yt-lite"]')) return; // Skip YouTube thumbnails

                        img.style.cursor = 'pointer';
                        img.addEventListener('click', function(e) {
                            e.preventDefault();
                            e.stopPropagation();

                            var src = img.getAttribute('data-src') || img.src;
                            if (!src) return;

                            // Create simple lightbox
                            var overlay = document.createElement('div');
                            overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;' +
                                'background:rgba(0,0,0,0.9);z-index:10000;display:flex;align-items:center;' +
                                'justify-content:center;cursor:pointer;';

                            var fullImg = document.createElement('img');
                            fullImg.src = src;
                            fullImg.style.cssText = 'max-width:90%;max-height:90%;object-fit:contain;';

                            overlay.appendChild(fullImg);
                            overlay.addEventListener('click', function() { overlay.remove(); });
                            document.body.appendChild(overlay);
                        });
                    });
                }
                
                // Try to run immediately
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', function() {
                        setTimeout(initOfflineMode, 500);
                    });
                } else {
                    // DOM already loaded
                    setTimeout(initOfflineMode, 500);
                }

                // Also run after full page load
                window.addEventListener('load', function() {
                    setTimeout(initOfflineMode, 1000);
                });
            }
            
            // Function to activate tabs in offline mode
            function activateOfflineTabs() {
                console.log('[Offline Mode] Activating tabs...');

                // Helper to check if element is inside media/interactive components that should not be touched
                function isInsideMediaComponent(el) {
                    var parent = el;
                    while (parent) {
                        var cls = (parent.className || '').toString().toLowerCase();
                        var id = (parent.id || '').toLowerCase();
                        // Skip YouTube, lightbox, carousel, gallery, modal components
                        if (cls.includes('yt-lite') || cls.includes('youtube') || cls.includes('video') ||
                            cls.includes('lightbox') || cls.includes('gallery') || cls.includes('carousel') ||
                            cls.includes('modal') || cls.includes('popup') || cls.includes('overlay') ||
                            cls.includes('slider') || cls.includes('swiper') || cls.includes('fancybox') ||
                            id.includes('youtube') || id.includes('lightbox') || id.includes('gallery')) {
                            return true;
                        }
                        parent = parent.parentElement;
                    }
                    return false;
                }

                // Valid marketplace tab labels (case-insensitive)
                var validTabLabels = ['overview', 'reviews', 'pricing', 'privacy', 'support', 'versions', 'changelog'];

                function isValidTabButton(el) {
                    var text = (el.textContent || el.innerText || '').trim().toLowerCase();
                    return validTabLabels.some(function(label) {
                        return text === label || text.includes(label);
                    });
                }

                // Use more specific selectors - only actual tab roles, not generic links
                var tabButtons = document.querySelectorAll('[role="tab"], [data-tab], .tab-button, button[aria-controls]');
                var tabPanels = document.querySelectorAll('[role="tabpanel"], [data-tabpanel], .tab-panel');

                console.log('[Offline Mode] Found ' + tabButtons.length + ' tab buttons, ' + tabPanels.length + ' tab panels');

                // Process all found tab elements
                tabButtons.forEach(function(button) {
                    // Skip elements inside media components
                    if (isInsideMediaComponent(button)) {
                        console.log('[Offline Mode] Skipping button inside media component');
                        return;
                    }

                    // Only process buttons that look like actual tab navigation
                    if (!isValidTabButton(button) && !button.hasAttribute('aria-controls')) {
                        return;
                    }

                    // Clone element to remove old handlers
                    var newButton = button.cloneNode(true);
                    button.parentNode.replaceChild(newButton, button);

                    newButton.addEventListener('click', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        e.stopImmediatePropagation();

                        var targetId = newButton.getAttribute('aria-controls') ||
                                     newButton.getAttribute('data-tab') ||
                                     (newButton.getAttribute('href') || '').replace('#', '').split('?')[0];

                        var buttonText = (newButton.textContent || newButton.innerText || '').trim().toLowerCase();

                        console.log('[Offline Mode] Tab clicked: ' + buttonText + ', target: ' + targetId);

                        if (targetId) {
                            showTabById(targetId);
                        } else if (buttonText) {
                            showTab(buttonText);
                        }
                        
                        return false;
                    }, true); // useCapture = true for priority
                });
                
                // Fallback: only look for nav links if no tab buttons were found
                // Use much more restrictive criteria
                if (tabButtons.length === 0) {
                    var navLinks = document.querySelectorAll('nav a, .nav-link');
                    console.log('[Offline Mode] Found ' + navLinks.length + ' navigation links (fallback)');

                    navLinks.forEach(function(link) {
                        // Skip elements inside media components
                        if (isInsideMediaComponent(link)) {
                            return;
                        }

                        var linkText = (link.textContent || link.innerText || '').trim().toLowerCase();

                        // Only handle exact marketplace tab labels
                        if (linkText && validTabLabels.some(function(label) { return linkText === label; })) {
                            var newLink = link.cloneNode(true);
                            link.parentNode.replaceChild(newLink, link);

                            newLink.addEventListener('click', function(e) {
                                e.preventDefault();
                                e.stopPropagation();
                                e.stopImmediatePropagation();
                                console.log('[Offline Mode] Tab clicked: ' + linkText);
                                showTab(linkText);
                                return false;
                            }, true);
                        }
                    });
                }

                console.log('[Offline Mode] Tabs activated');
            }

            function showTab(tabName) {
                console.log('[Offline Mode] Showing tab: ' + tabName);

                // Only hide actual tab panels, not all content
                var allPanels = document.querySelectorAll('[role="tabpanel"], [data-tabpanel], .tab-panel');
                allPanels.forEach(function(panel) {
                    panel.style.display = 'none';
                    panel.setAttribute('aria-hidden', 'true');
                });

                // Only update actual tab buttons
                var allButtons = document.querySelectorAll('[role="tab"], [data-tab], .tab-button, button[aria-controls]');
                allButtons.forEach(function(btn) {
                    btn.classList.remove('active', 'selected', 'is-active', 'is-selected');
                    btn.setAttribute('aria-selected', 'false');
                    btn.setAttribute('aria-current', 'false');
                });
                
                // Show target panel (heuristic search)
                var keywords = {
                    'overview': ['overview', 'description', 'main', 'about'],
                    'reviews': ['review', 'rating', 'feedback', 'comment'],
                    'pricing': ['pricing', 'price', 'cost', 'plan', 'purchase'],
                    'privacy': ['privacy', 'security', 'data', 'gdpr'],
                    'support': ['support', 'help', 'contact', 'faq'],
                    'installation': ['install', 'setup', 'guide', 'getting started']
                };
                
                var targetKeywords = keywords[tabName] || [tabName];
                var foundPanel = false;
                
                allPanels.forEach(function(panel) {
                    var panelText = (panel.textContent || '').toLowerCase();
                    var panelId = (panel.id || '').toLowerCase();
                    var panelClass = (panel.className || '').toLowerCase();
                    var panelDataTestId = (panel.getAttribute('data-testid') || '').toLowerCase();
                    
                    if (targetKeywords.some(function(kw) {
                        return panelText.includes(kw) || panelId.includes(kw) || panelClass.includes(kw) || panelDataTestId.includes(kw);
                    })) {
                        panel.style.display = 'block';
                        panel.setAttribute('aria-hidden', 'false');
                        foundPanel = true;
                        console.log('[Offline Mode] Found and showing panel: ' + (panelId || panelClass));
                    }
                });
                
                // If panel not found, show first available
                if (!foundPanel && allPanels.length > 0) {
                    allPanels[0].style.display = 'block';
                    allPanels[0].setAttribute('aria-hidden', 'false');
                    console.log('[Offline Mode] No specific panel found, showing first available');
                }
                
                // Update active button
                allButtons.forEach(function(btn) {
                    var btnText = (btn.textContent || btn.innerText || '').trim().toLowerCase();
                    if (btnText.includes(tabName) || targetKeywords.some(function(kw) { return btnText.includes(kw); })) {
                        btn.classList.add('active', 'selected');
                        btn.setAttribute('aria-selected', 'true');
                        btn.setAttribute('aria-current', 'page');
                    }
                });
            }
            
            function showTabById(targetId) {
                // Hide all panels
                var allPanels = document.querySelectorAll('[role="tabpanel"], [data-tabpanel], .tab-panel');
                allPanels.forEach(function(panel) {
                    panel.style.display = 'none';
                });
                
                // Show target panel
                var targetPanel = document.getElementById(targetId) || 
                                document.querySelector('[data-tabpanel="' + targetId + '"]');
                if (targetPanel) {
                    targetPanel.style.display = 'block';
                }
                
                // Update active buttons
                var allButtons = document.querySelectorAll('[role="tab"], [data-tab], .tab-button');
                allButtons.forEach(function(btn) {
                    var btnTarget = btn.getAttribute('aria-controls') || btn.getAttribute('data-tab');
                    if (btnTarget === targetId) {
                        btn.classList.add('active', 'selected');
                        btn.setAttribute('aria-selected', 'true');
                    } else {
                        btn.classList.remove('active', 'selected');
                        btn.setAttribute('aria-selected', 'false');
                    }
                });
            }
        })();
        """
        head.insert(0, patch_script)
        logger.debug("Added offline mode patches to beginning of page")

    def _fix_absolute_paths(self, soup: BeautifulSoup, base_url: str):
        """Fix absolute paths that start with drive letters (I:/, Z:/, etc.)"""
        fixed_count = 0
        removed_count = 0
        
        for tag in soup.find_all(True):
            for attr in ['src', 'href', 'srcset', 'data-src', 'data-href']:
                if tag.has_attr(attr):
                    value = tag.get(attr)
                    if not value:
                        continue
                    
                    # Fix paths starting with /I:/, /Z:/, I:/, Z:/, etc.
                    # These are absolute Windows paths that don't work in file:// protocol
                    if (value.startswith('/I:/') or value.startswith('I:/') or 
                        value.startswith('/Z:/') or value.startswith('Z:/') or 
                        value.startswith('/Z:\\') or value.startswith('Z:\\') or
                        value.startswith('/I:\\') or value.startswith('I:\\')):
                        
                        # Extract the actual path after drive letter
                        # /I:/amkt-frontend-static/... -> /amkt-frontend-static/...
                        # I:/amkt-frontend-static/... -> /amkt-frontend-static/...
                        if value.startswith('/I:/') or value.startswith('/Z:/'):
                            clean_path = value[3:]  # Remove first 3 chars (/I: or /Z:)
                        elif value.startswith('I:/') or value.startswith('Z:/'):
                            clean_path = value[2:]  # Remove first 2 chars (I: or Z:)
                        elif value.startswith('/I:\\') or value.startswith('/Z:\\'):
                            clean_path = value[4:]  # Remove first 4 chars (/I:\ or /Z:\)
                        elif value.startswith('I:\\') or value.startswith('Z:\\'):
                            clean_path = value[3:]  # Remove first 3 chars (I:\ or Z:\)
                        else:
                            clean_path = value
                        
                        # Now try to download the asset
                        if '/amkt-frontend-static/' in clean_path or '/gateway/' in clean_path:
                            if clean_path.endswith('.js') or clean_path.endswith('.css'):
                                # Try to construct proper URL and download
                                url_path = clean_path.lstrip('/')
                                abs_url = self._abs_url(base_url, url_path)
                                try:
                                    new_path = self._save_asset(abs_url, subfolder="js" if clean_path.endswith('.js') else "css")
                                    tag[attr] = new_path
                                    fixed_count += 1
                                    logger.debug(f"Fixed path: {value} -> {new_path}")
                                except Exception as e:
                                    logger.debug(f"Failed to download {abs_url}: {e}")
                                    tag[attr] = ""  # Remove broken link
                                    removed_count += 1
                            else:
                                tag[attr] = ""  # Remove non-JS/CSS gateway links
                                removed_count += 1
                        else:
                            # Try to download other assets
                            url_path = clean_path.lstrip('/')
                            abs_url = self._abs_url(base_url, url_path)
                            try:
                                new_path = self._save_asset(abs_url, subfolder="assets")
                                tag[attr] = new_path
                                fixed_count += 1
                            except Exception as e:
                                logger.debug(f"Failed to download {abs_url}: {e}")
                                tag[attr] = ""  # Remove broken link
                                removed_count += 1
        
        if fixed_count > 0 or removed_count > 0:
            logger.info(f"Fixed paths: {fixed_count}, removed broken links: {removed_count}")

    def _disable_error_scripts(self, soup: BeautifulSoup):
        """Remove or disable problematic scripts that cause errors in offline mode.

        IMPORTANT: Be conservative! Only remove scripts that are definitely problematic
        (analytics, tracking, cookie consent). Do NOT remove main application JavaScript.
        """
        scripts = soup.find_all("script")
        removed_count = 0
        disabled_count = 0

        # Only remove scripts from these specific problematic sources
        # Do NOT remove main application JS (which may be from marketplace.atlassian.com)
        problematic_src_patterns = [
            "onetrust",           # Cookie consent
            "statsig",            # A/B testing
            "optimizely",         # A/B testing
            "analytics",          # Analytics
            "gtag",               # Google Analytics
            "google-analytics",   # Google Analytics
            "segment.io",         # Analytics
            "hotjar",             # Analytics
            "px.ads.linkedin",    # LinkedIn tracking
            "facebook.com/tr",    # Facebook tracking
            "connect.facebook",   # Facebook SDK
        ]

        for script in scripts:
            if script.has_attr("src"):
                src = script.get("src", "")
                src_lower = src.lower()

                # Only remove scripts from definitely problematic sources
                if any(pattern in src_lower for pattern in problematic_src_patterns):
                    script.decompose()
                    removed_count += 1
                    logger.debug(f"Removed problematic script: {src}")
                # Remove scripts with broken Windows paths
                elif (src.startswith('/I:/') or src.startswith('I:/') or
                      src.startswith('/Z:/') or src.startswith('Z:/')):
                    script.decompose()
                    removed_count += 1
                    logger.debug(f"Removed script with invalid path: {src}")
            else:
                # Inline scripts - only disable specific problematic ones
                script_text = script.string or ""
                script_lower = script_text.lower()

                # Only disable small inline scripts that are clearly problematic
                if len(script_text) > 0 and len(script_text) < 500:
                    if any(pattern in script_lower for pattern in ["globalrequire", "onetrust", "statsig", "optimizely"]):
                        script.string = "// Disabled for offline mode"
                        disabled_count += 1
                        logger.debug(f"Disabled problematic inline script")
        
        if removed_count > 0 or disabled_count > 0:
            logger.info(f"Removed scripts: {removed_count}, disabled: {disabled_count}")

    def _process_css_file(self, css_abs_url: str, css_local_rel: str, base_for_css: str):
        if not self.offline:
            return
        local_path = (self.out_html.parent / css_local_rel).resolve()
        try:
            text = local_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return

        repl_map: Dict[str, str] = {}
        for url in set(_find_css_urls(text)):
            if _is_data_url(url):
                continue
            resolved = self._abs_url(base_for_css, url)
            local = self._save_asset(resolved, subfolder="css_assets")
            repl_map[url] = local

        new_text = _rewrite_css_urls(text, repl_map)
        try:
            local_path.write_text(new_text, encoding="utf-8")
        except (OSError, IOError) as e:
            logger.debug(f"Failed to write CSS file {local_path}: {e}")

    def _get_html_with_playwright(self, url: str, wait_seconds: int = 8, timeout: int = 90) -> Tuple[str, str]:
        """Gets page HTML after JavaScript execution via Playwright.

        If self._playwright_page is set, reuses that page instead of creating a new browser.
        This is much faster when processing many pages.
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

            # If we have a reusable page, use it
            if self._playwright_page is not None:
                logger.info("Using existing Playwright page (reused browser)...")
                page = self._playwright_page

                try:
                    page.goto(url, wait_until="load", timeout=timeout * 1000)
                    logger.debug("Page loaded successfully")
                except Exception as e:
                    logger.warning(f"Load timeout, trying domcontentloaded: {str(e)[:100]}")
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                    except Exception:
                        page.goto(url, timeout=30000)

                # Wait for content to load
                page.wait_for_timeout(wait_seconds * 1000)
                page.wait_for_timeout(3000)

                # Try to wait for main content to load
                try:
                    page.wait_for_selector('body', timeout=5000)
                    page.wait_for_timeout(5000)
                except PlaywrightTimeout:
                    pass

                html = page.content()
                final_url = page.url
                logger.info(f"Page loaded via Playwright (reused) ({len(html)} characters)")
                return html, final_url

            # Fallback: create new browser (original behavior)
            logger.info("Using Playwright to get fully loaded page...")

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
                    user_agent=_user_agent(),
                    viewport={'width': 1920, 'height': 1080}
                )

                # Block unnecessary resources
                def route_handler(route):
                    url_req = route.request.url
                    blocked_patterns = [
                        'analytics', 'tracking', 'doubleclick', 'googlesyndication',
                        'facebook.com/tr', 'optimizely.com', 'hotjar.com',
                        'googletagmanager.com', 'google-analytics.com'
                    ]
                    if any(pattern in url_req.lower() for pattern in blocked_patterns):
                        route.abort()
                    else:
                        route.continue_()

                context.route("**/*", route_handler)

                page = context.new_page()

                try:
                    page.goto(url, wait_until="load", timeout=timeout * 1000)
                    logger.debug("Page loaded successfully")
                except Exception as e:
                    logger.warning(f"Load timeout, trying domcontentloaded: {str(e)[:100]}")
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                    except Exception:
                        page.goto(url, timeout=30000)

                # Wait for content to load
                page.wait_for_timeout(wait_seconds * 1000)
                page.wait_for_timeout(3000)

                # Try to wait for main content to load
                try:
                    # Wait for body element
                    page.wait_for_selector('body', timeout=5000)
                    # Additional wait for dynamic content
                    page.wait_for_timeout(5000)
                except PlaywrightTimeout:
                    pass  # Timeout waiting for body is acceptable, page may still have content

                html = page.content()
                final_url = page.url

                browser.close()
                logger.info(f"Page loaded via Playwright ({len(html)} characters)")
                return html, final_url

        except ImportError:
            logger.warning("Playwright not installed")
            raise
        except Exception as e:
            logger.warning(f"Error using Playwright: {e}")
            raise

    def run(self, wait_seconds: int = 8, timeout: int = 90) -> SaveResult:
        logger.info(f"Downloading page: {self.url}")
        
        html = None
        base_url = self.url
        
        try:
            html, base_url = self._get_html_with_playwright(self.url, wait_seconds, timeout)
        except Exception as e:
            logger.warning(f"Failed to use Playwright: {e}")
            logger.info("Trying to use regular HTTP request...")
            resp = self.session.get(self.url, timeout=self.timeout)
            resp.raise_for_status()
            html = resp.text
            base_url = resp.url

        soup = BeautifulSoup(html, "lxml")
        self._inject_base_tag(soup, base_url)
        
        if self.offline:
            self._inject_offline_patches(soup)
            self._disable_error_scripts(soup)
            self._fix_absolute_paths(soup, base_url)

        # <img> - prioritize full resolution sources
        for img in soup.find_all("img"):
            # Check for data-src (often contains full resolution)
            if img.has_attr("data-src"):
                data_src = self._handle_src_like(base_url, img["data-src"], kind="img")
                # Use data-src as the main src if available
                if data_src and not _is_data_url(img.get("src", "")):
                    img["src"] = data_src
                del img["data-src"]

            # Process srcset first to potentially get a better image
            best_from_srcset = None
            if img.has_attr("srcset"):
                processed_srcset = self._process_srcset(base_url, img["srcset"])
                # In offline mode, _process_srcset returns just the best URL
                if self.offline and processed_srcset and not "," in processed_srcset:
                    best_from_srcset = processed_srcset
                img["srcset"] = processed_srcset

            # Process src
            if img.has_attr("src"):
                img["src"] = self._handle_src_like(base_url, img["src"], kind="img")

            # If we found a better image from srcset, use it as src
            if best_from_srcset:
                img["src"] = best_from_srcset

        # <link rel="stylesheet"> and icons
        for link in soup.find_all("link"):
            rel = ",".join(link.get("rel", [])).lower()
            href = link.get("href")
            if not href:
                continue
            if "stylesheet" in rel or ("preload" in rel and link.get("as") == "style"):
                new_href, abs_css = self._handle_asset_generic(base_url, href, subfolder="css")
                link["href"] = new_href
                if self.offline and abs_css and not _is_data_url(abs_css):
                    self._process_css_file(abs_css, new_href, base_for_css=abs_css)
            elif any(k in rel for k in ["icon", "shortcut icon", "apple-touch-icon", "mask-icon"]):
                new_href, _ = self._handle_asset_generic(base_url, href, subfolder="icons")
                link["href"] = new_href

        # <script src>
        for sc in soup.find_all("script"):
            src = sc.get("src")
            if src:
                new_src, _ = self._handle_asset_generic(base_url, src, subfolder="js")
                sc["src"] = new_src

        # media
        for tagname, attr, subfolder in [
            ("source", "src", "media"),
            ("video", "src", "media"),
            ("video", "poster", "media"),
            ("audio", "src", "media"),
            ("track", "src", "media"),
        ]:
            for t in soup.find_all(tagname):
                if t.has_attr(attr):
                    t[attr] = self._handle_src_like(base_url, t[attr], kind=subfolder)

        # save final HTML
        self.out_html.parent.mkdir(parents=True, exist_ok=True)
        out_html = str(soup)
        if not out_html.strip().startswith('<!DOCTYPE'):
            out_html = '<!DOCTYPE html>\n' + out_html
        # Disable React hydration to prevent 404 errors when viewing offline
        out_html = out_html.replace('"shouldHydrate":true', '"shouldHydrate":false')
        out_html = out_html.replace("'shouldHydrate':true", "'shouldHydrate':false")
        self.out_html.write_text(out_html, encoding="utf-8", errors="replace")
        logger.info(f"Page saved: {self.out_html}")

        return SaveResult(
            output_html=str(self.out_html),
            assets_dir=str(self.assets_dir) if (self.offline and self.assets_dir) else None,
            mode="OFFLINE" if self.offline else "ONLINE",
        )

    def _handle_asset_generic(self, base_url: str, href: str, subfolder: str):
        abs_u = self._abs_url(base_url, href)
        if not abs_u:
            return href, abs_u
        if not self.offline:
            return abs_u, abs_u
        local_rel = self._save_asset(abs_u, subfolder=subfolder)
        return local_rel, abs_u


# ------------------------------ public API -----------------------------


class PlaywrightBrowserManager:
    """
    Manager for reusing a single Playwright browser across multiple page saves.

    Usage:
        with PlaywrightBrowserManager() as manager:
            for url in urls:
                save_webpage_full(url, output, playwright_page=manager.page)

    This is MUCH faster than creating a new browser for each page.
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright not installed, browser reuse not available")
            return self

        try:
            logger.info("Starting reusable Playwright browser...")
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox'
                ]
            )
            self._context = self._browser.new_context(
                user_agent=_user_agent(),
                viewport={'width': 1920, 'height': 1080}
            )

            # Block unnecessary resources at context level
            def route_handler(route):
                url_req = route.request.url
                blocked_patterns = [
                    'analytics', 'tracking', 'doubleclick', 'googlesyndication',
                    'facebook.com/tr', 'optimizely.com', 'hotjar.com',
                    'googletagmanager.com', 'google-analytics.com'
                ]
                if any(pattern in url_req.lower() for pattern in blocked_patterns):
                    route.abort()
                else:
                    route.continue_()

            self._context.route("**/*", route_handler)
            self._page = self._context.new_page()
            logger.info("Playwright browser started and ready for reuse")
        except Exception as e:
            logger.warning(f"Failed to start reusable browser: {e}")
            logger.warning("Will fall back to creating new browser for each page")
            # Clean up partial state
            if self._browser:
                try:
                    self._browser.close()
                except Exception as e:
                    logger.debug(f"Error closing browser during cleanup: {e}")
            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception as e:
                    logger.debug(f"Error stopping playwright during cleanup: {e}")
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            logger.info("Closing reusable Playwright browser...")
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        return False

    @property
    def page(self):
        """Returns the reusable page, or None if browser not available."""
        return self._page

    @property
    def is_available(self) -> bool:
        """Check if the browser is available and ready."""
        return self._page is not None


def save_webpage_full(
    url: str,
    output: str,
    *,
    offline: bool = True,
    assets_dir: Optional[str] = None,
    timeout: int = 90,
    wait_seconds: int = 10,
    session: Optional[requests.Session] = None,
    playwright_page=None,
) -> SaveResult:
    """
    Save page to local HTML (full version).

    Args:
        url: source URL
        output: path to HTML file
        offline: if True - download all resources and rewrite paths to local
        assets_dir: folder for resources (if None - 'assets')
        timeout: HTTP request timeout in seconds
        wait_seconds: wait time after page load for JS
        session: optional requests session
        playwright_page: optional reusable Playwright page (for batch processing)

    Returns:
        SaveResult with paths to saved files
    """
    out_html = Path(output).resolve()
    assets = Path(assets_dir).resolve() if assets_dir else (out_html.parent / "assets")
    saver = _Saver(url=url, out_html=out_html, assets_dir=assets, offline=offline, timeout=timeout, session=session, playwright_page=playwright_page)
    return saver.run(wait_seconds=wait_seconds, timeout=timeout)

