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
                // Блокируем все ошибки связанные с загрузкой ресурсов
                var originalConsoleError = console.error;
                console.error = function() {
                    var args = Array.prototype.slice.call(arguments);
                    var message = args.join(' ');
                    // Подавляем ошибки связанные с file://, CORS, и отсутствующими файлами
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
                        // Подавляем эти ошибки
                        return;
                    }
                    // Для остальных ошибок используем оригинальный console.error
                    originalConsoleError.apply(console, args);
                };
                
                window.addEventListener('error', function(e) {
                    var errorMsg = (e.message || '').toString();
                    var errorSrc = (e.filename || e.source || '').toString();
                    
                    // Подавляем ошибки связанные с file://, CORS, отсутствующими файлами
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
                
                // Блокируем показ сообщений об ошибках от API
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
            
            // Скрываем элементы с ошибками API после загрузки
            if (typeof document !== 'undefined' && document.addEventListener) {
                // Запускаем сразу, не ждем DOMContentLoaded
                function initOfflineMode() {
                    // Скрываем сообщения об ошибках API
                    var errorElements = document.querySelectorAll('[class*="error"], [class*="outage"], [id*="error"], [id*="outage"]');
                    errorElements.forEach(function(el) {
                        var text = el.textContent || el.innerText || '';
                        if (text.includes('outage') || text.includes('experiencing') || text.includes('error')) {
                            el.style.display = 'none';
                        }
                    });
                    
                    // Активируем работу вкладок (tabs) в офлайн-режиме
                    activateOfflineTabs();
                }
                
                // Пытаемся запустить сразу
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', function() {
                        setTimeout(initOfflineMode, 500);
                    });
                } else {
                    // DOM уже загружен
                    setTimeout(initOfflineMode, 500);
                }
                
                // Также запускаем после полной загрузки
                window.addEventListener('load', function() {
                    setTimeout(initOfflineMode, 1000);
                });
            }
            
            // Функция для активации вкладок в офлайн-режиме
            function activateOfflineTabs() {
                console.log('[Offline Mode] Activating tabs...');
                
                // Ищем все элементы вкладок - более широкий поиск
                var tabButtons = document.querySelectorAll('[role="tab"], [data-tab], .tab-button, button[aria-controls], a[role="tab"], nav a, [class*="tab"]');
                var tabPanels = document.querySelectorAll('[role="tabpanel"], [data-tabpanel], .tab-panel, [id*="tab"], [data-testid*="tab"]');
                
                console.log('[Offline Mode] Found ' + tabButtons.length + ' tab buttons, ' + tabPanels.length + ' tab panels');
                
                // Обработка всех найденных элементов вкладок
                tabButtons.forEach(function(button) {
                    // Клонируем элемент чтобы удалить старые обработчики
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
                    }, true); // useCapture = true для приоритета
                });
                
                // Если не нашли стандартные вкладки, ищем по тексту
                if (tabButtons.length === 0) {
                    var navLinks = document.querySelectorAll('nav a, .nav-link, [class*="tab"], [class*="Tab"], a[href*="#"]');
                    console.log('[Offline Mode] Found ' + navLinks.length + ' navigation links');
                    
                    navLinks.forEach(function(link) {
                        var linkText = (link.textContent || link.innerText || '').trim().toLowerCase();
                        
                        if (linkText && (
                            linkText.includes('overview') ||
                            linkText.includes('reviews') ||
                            linkText.includes('pricing') ||
                            linkText.includes('privacy') ||
                            linkText.includes('support') ||
                            linkText.includes('installation') ||
                            linkText.includes('documentation')
                        )) {
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
                
                // Скрываем все панели - более широкий поиск
                var allPanels = document.querySelectorAll('[role="tabpanel"], [data-tabpanel], .tab-panel, [class*="content"], [class*="panel"], [class*="Content"], [class*="Panel"], section, main > div, [data-testid*="panel"]');
                allPanels.forEach(function(panel) {
                    panel.style.display = 'none';
                    panel.setAttribute('aria-hidden', 'true');
                });
                
                // Убираем активный класс со всех кнопок
                var allButtons = document.querySelectorAll('[role="tab"], [data-tab], .tab-button, button[aria-controls], nav a, [class*="tab"]');
                allButtons.forEach(function(btn) {
                    btn.classList.remove('active', 'selected', 'is-active', 'is-selected');
                    btn.setAttribute('aria-selected', 'false');
                    btn.setAttribute('aria-current', 'false');
                });
                
                // Показываем нужную панель (эвристический поиск)
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
                
                // Если не нашли панель, показываем первую доступную
                if (!foundPanel && allPanels.length > 0) {
                    allPanels[0].style.display = 'block';
                    allPanels[0].setAttribute('aria-hidden', 'false');
                    console.log('[Offline Mode] No specific panel found, showing first available');
                }
                
                // Обновляем активную кнопку
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
                // Скрываем все панели
                var allPanels = document.querySelectorAll('[role="tabpanel"], [data-tabpanel], .tab-panel');
                allPanels.forEach(function(panel) {
                    panel.style.display = 'none';
                });
                
                // Показываем целевую панель
                var targetPanel = document.getElementById(targetId) || 
                                document.querySelector('[data-tabpanel="' + targetId + '"]');
                if (targetPanel) {
                    targetPanel.style.display = 'block';
                }
                
                // Обновляем активные кнопки
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
        logger.debug("Добавлены патчи для офлайн-режима в начало страницы")

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
                                    logger.debug(f"Исправлен путь: {value} -> {new_path}")
                                except Exception as e:
                                    logger.debug(f"Не удалось скачать {abs_url}: {e}")
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
                                logger.debug(f"Не удалось скачать {abs_url}: {e}")
                                tag[attr] = ""  # Remove broken link
                                removed_count += 1
        
        if fixed_count > 0 or removed_count > 0:
            logger.info(f"Исправлено путей: {fixed_count}, удалено битых ссылок: {removed_count}")

    def _disable_error_scripts(self, soup: BeautifulSoup):
        """Remove or disable problematic scripts that cause errors in offline mode."""
        scripts = soup.find_all("script")
        removed_count = 0
        disabled_count = 0
        
        for script in scripts:
            script_text = script.string or ""
            error_patterns = [
                "404", "not found", "error", "catch",
                "window.location", "redirect",
                "api.atlassian.com", "marketplace.atlassian.com/api",
                "marketplace.atlassian.com/rest",
                "fetch(", "XMLHttpRequest",
                "/rest/", "/api/", "gateway/",
                "amkt-frontend-static", "globalRequire",
                "onetrust", "cookie-integrator",
                "statsig", "optimizely",
            ]
            script_lower = script_text.lower()
            has_error_handling = any(pattern in script_lower for pattern in error_patterns)
            
            if script.has_attr("src"):
                src = script.get("src", "")
                src_lower = src.lower()
                # Remove scripts with problematic paths or URLs
                if (any(pattern in src_lower for pattern in ["api", "analytics", "track", "error", "rest", "gateway", "marketplace", "amkt-frontend", "onetrust", "statsig", "optimizely"]) or
                    src.startswith('/I:/') or src.startswith('I:/') or
                    src.startswith('/Z:/') or src.startswith('Z:/')):
                    script.decompose()
                    removed_count += 1
                    logger.debug(f"Удалён проблемный скрипт: {src}")
            elif has_error_handling and len(script_text) > 500:
                script.decompose()
                removed_count += 1
                logger.debug(f"Удалён проблемный inline скрипт (длина: {len(script_text)})")
            elif len(script_text) > 0 and len(script_text) < 500:
                # For small scripts, try to disable problematic code instead of removing
                if any(pattern in script_lower for pattern in ["globalRequire", "onetrust", "statsig"]):
                    # Replace problematic code with empty function
                    script.string = "// Disabled for offline mode"
                    disabled_count += 1
                    logger.debug(f"Отключён проблемный inline скрипт")
        
        if removed_count > 0 or disabled_count > 0:
            logger.info(f"Удалено скриптов: {removed_count}, отключено: {disabled_count}")

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
                
                # Ждем загрузки контента
                page.wait_for_timeout(wait_seconds * 1000)
                page.wait_for_timeout(3000)
                
                # Пытаемся дождаться загрузки основного контента
                try:
                    # Ждем появления основного контента страницы
                    page.wait_for_selector('body', timeout=5000)
                    # Дополнительное ожидание для загрузки динамического контента
                    page.wait_for_timeout(5000)
                except Exception:
                    # Если не удалось дождаться, продолжаем
                    pass
                
                html = page.content()
                final_url = page.url
                
                browser.close()
                logger.info(f"Страница загружена через Playwright ({len(html)} символов)")
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
        logger.info(f"Страница сохранена: {self.out_html}")

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

