# -*- coding: utf-8 -*-
"""
Интегрированный модуль сохранения веб-страниц из старой версии.
Полная версия с поддержкой Playwright и скачиванием всех ресурсов.
"""

from __future__ import annotations

import os
import re
import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from utils.logger import get_logger

logger = get_logger('description_downloader')

__all__ = ["save_webpage_full", "SaveResult"]


@dataclass
class SaveResult:
    """Результат сохранения страницы."""
    output_html: str           # путь к сохранённому HTML
    assets_dir: Optional[str]  # папка с ресурсами (None в онлайн-режиме)
    mode: str                  # "OFFLINE" или "ONLINE"


# ------------------------ вспомогательные функции ------------------------

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


# CSS url() обработка
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


# ------------------------------ ядро -------------------------------------

class _Saver:
    def __init__(self, url: str, out_html: Path, assets_dir: Optional[Path], offline: bool, timeout: int, session: Optional[requests.Session] = None):
        self.url = url
        self.out_html = out_html
        self.assets_dir = assets_dir
        self.offline = offline
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": _user_agent()})
        self._downloaded: Dict[str, str] = {}  # abs_url -> rel_path/from html
        self._playwright_resources: List[str] = []  # Ресурсы, найденные через Playwright

    def _abs_url(self, base: str, maybe: str) -> str:
        if not maybe:
            return ""
        if _is_data_url(maybe):
            return maybe
        return urljoin(base, maybe)

    def _save_asset(self, abs_url: str, subfolder: str = "") -> str:
        """Скачивает ресурс и возвращает относительный путь для HTML/CSS."""
        if _is_data_url(abs_url):
            return abs_url
        if abs_url in self._downloaded:
            return self._downloaded[abs_url]
        try:
            resp = self.session.get(abs_url, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as e:
            logger.debug(f"Не удалось скачать ресурс {abs_url}: {e}")
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
        logger.debug(f"Скачан ресурс: {abs_url} -> {target.name}")

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
        
        logger.debug(f"Относительный путь к ресурсу: {rel_path} (из {abs_url})")
        
        self._downloaded[abs_url] = rel_path
        return rel_path

    def _handle_src_like(self, base_url: str, value: str, kind: str = "") -> str:
        abs_u = self._abs_url(base_url, value)
        if not abs_u:
            return value
        if not self.offline:
            return abs_u
        sub = {"img": "img", "media": "media"}.get(kind, "assets")
        return self._save_asset(abs_u, subfolder=sub)

    def _process_srcset(self, base_url: str, srcset_value: str) -> str:
        parts = []
        for item in (srcset_value or "").split(","):
            item = item.strip()
            if not item:
                continue
            tokens = item.split()
            url_part = tokens[0]
            desc = " ".join(tokens[1:]) if len(tokens) > 1 else ""
            new_url = self._handle_src_like(base_url, url_part, kind="img")
            parts.append((new_url, desc))
        return ", ".join((" ".join([u, d]).strip() for u, d in parts))

    def _inject_base_tag(self, soup: BeautifulSoup, base_url: str):
        head = soup.find("head")
        if not head:
            head = soup.new_tag("head")
            soup.html.insert(0, head)

        for b in head.find_all("base"):
            b.decompose()

        if self.offline:
            pass
        else:
            base = soup.new_tag("base", href=base_url)
            head.insert(0, base)

    def _inject_offline_patches(self, soup: BeautifulSoup):
        """Вставляет патчи для блокировки API-вызовов в самое начало страницы."""
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
                    if (url && (
                        url.includes('api.atlassian.com') ||
                        url.includes('gateway/') ||
                        url.includes('/api/') ||
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
                        if (url && (
                            url.includes('api.atlassian.com') ||
                            url.includes('gateway/') ||
                            url.includes('/api/') ||
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
                window.addEventListener('error', function(e) {
                    if (e.message && (
                        e.message.includes('ChunkLoadError') ||
                        e.message.includes('Failed to fetch') ||
                        e.message.includes('net::ERR')
                    )) {
                        e.preventDefault();
                        e.stopPropagation();
                        console.log('[Offline Mode] Suppressed error:', e.message);
                        return false;
                    }
                }, true);
            }
        })();
        """
        head.insert(0, patch_script)
        logger.debug("Добавлены патчи для офлайн-режима в начало страницы")

    def _fix_absolute_paths(self, soup: BeautifulSoup, base_url: str):
        for tag in soup.find_all(True):
            for attr in ['src', 'href', 'srcset', 'data-src', 'data-href']:
                if tag.has_attr(attr):
                    value = tag.get(attr)
                    if not value:
                        continue
                    if value.startswith('/Z:/') or value.startswith('Z:/') or value.startswith('/Z:\\'):
                        if '/amkt-frontend-static/' in value or '/gateway/' in value:
                            if value.endswith('.js') or value.endswith('.css'):
                                filename = os.path.basename(value.split('?')[0])
                                if '/amkt-frontend-static/' in value:
                                    abs_url = self._abs_url(base_url, value)
                                    new_path = self._save_asset(abs_url, subfolder="js" if value.endswith('.js') else "css")
                                    tag[attr] = new_path
                                    logger.debug(f"Исправлен путь: {value} -> {new_path}")
                                else:
                                    tag[attr] = ""
                            else:
                                tag[attr] = ""
                        else:
                            abs_url = self._abs_url(base_url, value)
                            try:
                                new_path = self._save_asset(abs_url, subfolder="assets")
                                tag[attr] = new_path
                            except:
                                tag[attr] = ""

    def _disable_error_scripts(self, soup: BeautifulSoup):
        scripts = soup.find_all("script")
        for script in scripts:
            script_text = script.string or ""
            error_patterns = [
                "404", "not found", "error", "catch",
                "window.location", "redirect",
                "api.atlassian.com", "marketplace.atlassian.com/api",
                "fetch(", "XMLHttpRequest",
            ]
            script_lower = script_text.lower()
            has_error_handling = any(pattern in script_lower for pattern in error_patterns)
            
            if script.has_attr("src"):
                src = script.get("src", "")
                if any(pattern in src.lower() for pattern in ["api", "analytics", "track", "error"]):
                    script.decompose()
                    logger.debug(f"Удалён проблемный скрипт: {src}")
            elif has_error_handling and len(script_text) > 500:
                script.decompose()

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
        except Exception:
            pass

    def _get_html_with_playwright(self, url: str, wait_seconds: int = 8, timeout: int = 90) -> Tuple[str, str]:
        """Получает HTML страницы после выполнения JavaScript через Playwright."""
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
            
            logger.info("Использование Playwright для получения полностью загруженной страницы...")
            
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
                
                page.wait_for_timeout(wait_seconds * 1000)
                page.wait_for_timeout(3000)
                
                html = page.content()
                final_url = page.url
                
                browser.close()
                logger.success(f"Страница загружена через Playwright ({len(html)} символов)")
                return html, final_url
                
        except ImportError:
            logger.warning("Playwright не установлен")
            raise
        except Exception as e:
            logger.warning(f"Ошибка при использовании Playwright: {e}")
            raise

    def run(self, wait_seconds: int = 8, timeout: int = 90) -> SaveResult:
        logger.info(f"Скачивание страницы: {self.url}")
        
        html = None
        base_url = self.url
        
        try:
            html, base_url = self._get_html_with_playwright(self.url, wait_seconds, timeout)
        except Exception as e:
            logger.warning(f"Не удалось использовать Playwright: {e}")
            logger.info("Пробуем использовать обычный HTTP-запрос...")
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

        # <img>
        for img in soup.find_all("img"):
            if img.has_attr("src"):
                img["src"] = self._handle_src_like(base_url, img["src"], kind="img")
            if img.has_attr("srcset"):
                img["srcset"] = self._process_srcset(base_url, img["srcset"])

        # <link rel="stylesheet"> и иконки
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

        # медиа
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

        # сохранить итоговый HTML
        self.out_html.parent.mkdir(parents=True, exist_ok=True)
        out_html = str(soup)
        if not out_html.strip().startswith('<!DOCTYPE'):
            out_html = '<!DOCTYPE html>\n' + out_html
        self.out_html.write_text(out_html, encoding="utf-8", errors="replace")
        logger.success(f"Страница сохранена: {self.out_html}")

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


# ------------------------------ публичный API -----------------------------

def save_webpage_full(
    url: str,
    output: str,
    *,
    offline: bool = True,
    assets_dir: Optional[str] = None,
    timeout: int = 90,
    wait_seconds: int = 10,
    session: Optional[requests.Session] = None,
) -> SaveResult:
    """
    Сохранить страницу в локальный HTML (полная версия из старого кода).
    
    Args:
        url: исходная ссылка
        output: путь к HTML-файлу
        offline: если True — скачать все ресурсы и переписать пути на локальные
        assets_dir: папка для ресурсов (если None — 'assets')
        timeout: таймаут HTTP-запросов, секунд
        wait_seconds: время ожидания после загрузки страницы для JS
        session: опциональная сессия requests
        
    Returns:
        SaveResult с путями к сохранённым файлам
    """
    out_html = Path(output).resolve()
    assets = Path(assets_dir).resolve() if assets_dir else (out_html.parent / "assets")
    saver = _Saver(url=url, out_html=out_html, assets_dir=assets, offline=offline, timeout=timeout, session=session)
    return saver.run(wait_seconds=wait_seconds, timeout=timeout)

