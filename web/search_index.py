"""Search index for plugin descriptions and release notes."""

import os
import json
import re
import hashlib
from typing import Dict, List, Optional, Set
from pathlib import Path
from bs4 import BeautifulSoup
from config import settings
from utils.logger import get_logger

logger = get_logger('web')


def strip_html_tags(html_text: str) -> str:
    """Remove HTML tags from text."""
    if not html_text:
        return ''
    
    # Use BeautifulSoup to extract text
    soup = BeautifulSoup(html_text, 'html.parser')
    text = soup.get_text(separator=' ', strip=True)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_text_from_html_file(html_path: Path) -> str:
    """Extract plain text from HTML file."""
    try:
        with open(html_path, 'r', encoding='utf-8', errors='replace') as f:
            html_content = f.read()
        return strip_html_tags(html_content)
    except Exception as e:
        logger.debug(f"Error reading HTML file {html_path}: {str(e)}")
        return ''


def fuzzy_match(query: str, text: str, threshold: float = 0.6) -> bool:
    """
    Simple fuzzy matching using word overlap.
    
    Args:
        query: Search query
        text: Text to search in
        threshold: Minimum similarity threshold (0.0 to 1.0)
    
    Returns:
        True if similarity is above threshold
    """
    query_words = set(query.lower().split())
    text_words = set(text.lower().split())
    
    if not query_words:
        return False
    
    # Calculate Jaccard similarity (intersection over union)
    intersection = len(query_words & text_words)
    union = len(query_words | text_words)
    
    if union == 0:
        return False
    
    similarity = intersection / union
    
    # Also check if all query words appear in text (even if not exact match)
    if similarity >= threshold:
        return True
    
    # Check if all query words are substrings of text words
    all_words_found = True
    for qw in query_words:
        found = False
        for tw in text_words:
            if qw in tw or tw in qw:
                found = True
                break
        if not found:
            all_words_found = False
            break
    
    if all_words_found:
        return True
    
    return similarity >= threshold


def find_match_context(query: str, text: str, context_size: int = 150) -> str:
    """Find and extract context around match."""
    query_lower = query.lower()
    text_lower = text.lower()
    
    # Try exact match first
    pos = text_lower.find(query_lower)
    if pos >= 0:
        start = max(0, pos - context_size)
        end = min(len(text), pos + len(query) + context_size)
        context = text[start:end]
        if start > 0:
            context = '...' + context
        if end < len(text):
            context = context + '...'
        return context
    
    # Try fuzzy match - find first word
    query_words = query_lower.split()
    if query_words:
        first_word = query_words[0]
        pos = text_lower.find(first_word)
        if pos >= 0:
            start = max(0, pos - context_size)
            end = min(len(text), pos + len(query) + context_size)
            context = text[start:end]
            if start > 0:
                context = '...' + context
            if end < len(text):
                context = context + '...'
            return context
    
    # Return beginning of text
    return text[:context_size * 2] + '...' if len(text) > context_size * 2 else text


class SearchIndex:
    """Search index for plugin descriptions and release notes."""
    
    def __init__(self, index_file: Optional[Path] = None):
        """
        Initialize search index.
        
        Args:
            index_file: Path to index cache file (optional)
        """
        self.index_file = index_file or Path(settings.DESCRIPTIONS_DIR) / '.search_index.json'
        self.index: Dict[str, Dict] = {}
        self.index_hash: str = ''
    
    def _calculate_index_hash(self) -> str:
        """Calculate hash of all description files to detect changes."""
        descriptions_dir = Path(settings.DESCRIPTIONS_DIR)
        if not descriptions_dir.exists():
            return ''
        
        file_hashes = []
        for item in sorted(descriptions_dir.iterdir()):
            if item.is_dir():
                # Check for JSON and HTML files
                for file_path in sorted(item.rglob('*.json')):
                    try:
                        stat = file_path.stat()
                        file_hashes.append(f"{file_path}:{stat.st_mtime}:{stat.st_size}")
                    except:
                        pass
                for file_path in sorted(item.rglob('*.html')):
                    try:
                        stat = file_path.stat()
                        file_hashes.append(f"{file_path}:{stat.st_mtime}:{stat.st_size}")
                    except:
                        pass
        
        hash_str = '|'.join(file_hashes)
        return hashlib.md5(hash_str.encode('utf-8')).hexdigest()
    
    def load_index(self) -> bool:
        """Load index from cache file."""
        if not self.index_file.exists():
            return False
        
        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            stored_hash = data.get('hash', '')
            current_hash = self._calculate_index_hash()
            
            if stored_hash == current_hash:
                self.index = data.get('index', {})
                self.index_hash = stored_hash
                logger.info(f"Loaded search index from cache ({len(self.index)} entries)")
                return True
            else:
                logger.info("Search index cache is outdated, will rebuild")
                return False
        except Exception as e:
            logger.warning(f"Error loading search index: {str(e)}")
            return False
    
    def save_index(self):
        """Save index to cache file."""
        try:
            self.index_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'hash': self.index_hash,
                'index': self.index
            }
            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved search index to {self.index_file}")
        except Exception as e:
            logger.error(f"Error saving search index: {str(e)}")
    
    def build_index(self, metadata_store):
        """Build search index from all descriptions and release notes."""
        logger.info("Building search index...")
        self.index = {}
        descriptions_dir = Path(settings.DESCRIPTIONS_DIR)
        
        if not descriptions_dir.exists():
            logger.warning(f"Descriptions directory does not exist: {descriptions_dir}")
            return
        
        # Index descriptions from JSON files
        for item in descriptions_dir.iterdir():
            if not item.is_dir():
                continue
            
            addon_key = item.name.replace('_', '.')
            
            # Search in JSON description files
            json_files = list(item.glob('*.json'))
            for json_file in json_files:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        desc_data = json.load(f)
                    
                    # Extract text from various fields
                    search_text = ''
                    
                    # Summary
                    summary = desc_data.get('summary', '')
                    if summary:
                        search_text += ' ' + strip_html_tags(str(summary))
                    
                    # Overview
                    overview = desc_data.get('overview', {})
                    if isinstance(overview, dict):
                        for key in ['body', 'text', 'content', 'html']:
                            val = overview.get(key, '')
                            if val:
                                search_text += ' ' + strip_html_tags(str(val))
                    elif isinstance(overview, str):
                        search_text += ' ' + strip_html_tags(overview)
                    
                    # Highlights
                    highlights = desc_data.get('highlights', {})
                    if isinstance(highlights, dict):
                        for key in ['body', 'text', 'content', 'html']:
                            val = highlights.get(key, '')
                            if val:
                                search_text += ' ' + strip_html_tags(str(val))
                    elif isinstance(highlights, str):
                        search_text += ' ' + strip_html_tags(highlights)
                    
                    # Addon info
                    addon = desc_data.get('addon', {})
                    if isinstance(addon, dict):
                        for key in ['summary', 'description']:
                            val = addon.get(key, '')
                            if val:
                                search_text += ' ' + strip_html_tags(str(val))
                    
                    if search_text.strip():
                        if addon_key not in self.index:
                            self.index[addon_key] = {
                                'json_text': '',
                                'html_text': '',
                                'release_notes_text': ''
                            }
                        self.index[addon_key]['json_text'] = search_text.strip()
                except Exception as e:
                    logger.debug(f"Error indexing JSON file {json_file}: {str(e)}")
            
            # Index full page HTML files
            full_page_dir = item / 'full_page'
            if full_page_dir.exists():
                html_files = list(full_page_dir.glob('*.html'))
                for html_file in html_files:
                    if html_file.name == 'index.html' or 'index' in html_file.name.lower():
                        try:
                            html_text = extract_text_from_html_file(html_file)
                            if html_text:
                                if addon_key not in self.index:
                                    self.index[addon_key] = {
                                        'json_text': '',
                                        'html_text': '',
                                        'release_notes_text': ''
                                    }
                                # Append to existing HTML text
                                if self.index[addon_key]['html_text']:
                                    self.index[addon_key]['html_text'] += ' ' + html_text
                                else:
                                    self.index[addon_key]['html_text'] = html_text
                        except Exception as e:
                            logger.debug(f"Error indexing HTML file {html_file}: {str(e)}")
        
        # Index release notes from database
        all_apps = metadata_store.get_all_apps()
        for app_info in all_apps:
            addon_key = app_info.get('addon_key')
            versions = metadata_store.get_app_versions(addon_key)
            
            release_notes_texts = []
            for version in versions:
                release_notes = version.get('release_notes', '')
                if release_notes:
                    release_notes_texts.append(strip_html_tags(release_notes))
            
            if release_notes_texts:
                if addon_key not in self.index:
                    self.index[addon_key] = {
                        'json_text': '',
                        'html_text': '',
                        'release_notes_text': ''
                    }
                self.index[addon_key]['release_notes_text'] = ' '.join(release_notes_texts)
        
        self.index_hash = self._calculate_index_hash()
        logger.info(f"Built search index with {len(self.index)} entries")
    
    def search(self, query: str, metadata_store, use_fuzzy: bool = True) -> List[Dict]:
        """
        Search in indexed content.
        
        Args:
            query: Search query
            metadata_store: MetadataStore instance
            use_fuzzy: Whether to use fuzzy matching
        
        Returns:
            List of search results
        """
        if not query or not query.strip():
            return []
        
        query_lower = query.lower().strip()
        query_words = query_lower.split()
        results = []
        seen_keys: Set[str] = set()
        
        for addon_key, indexed_data in self.index.items():
            if addon_key in seen_keys:
                continue
            
            app = metadata_store.get_app_by_key(addon_key)
            if not app:
                continue
            
            # Combine all text sources
            all_text = ' '.join([
                indexed_data.get('json_text', ''),
                indexed_data.get('html_text', ''),
                indexed_data.get('release_notes_text', '')
            ]).lower()
            
            # Check for match
            matched = False
            match_type = None
            match_context = ''
            release_notes_context = ''
            
            # Check JSON text
            json_text = indexed_data.get('json_text', '').lower()
            if json_text:
                if query_lower in json_text or (use_fuzzy and fuzzy_match(query, json_text)):
                    matched = True
                    if not match_type:
                        match_type = 'description'
                    if not match_context:
                        match_context = find_match_context(query, indexed_data.get('json_text', ''))
            
            # Check HTML text
            html_text = indexed_data.get('html_text', '').lower()
            if html_text:
                if query_lower in html_text or (use_fuzzy and fuzzy_match(query, html_text)):
                    matched = True
                    if not match_type:
                        match_type = 'description'
                    elif match_type == 'release_notes':
                        match_type = 'description_and_release_notes'
                    if not match_context:
                        match_context = find_match_context(query, indexed_data.get('html_text', ''))
            
            # Check release notes
            release_notes_text = indexed_data.get('release_notes_text', '').lower()
            if release_notes_text:
                if query_lower in release_notes_text or (use_fuzzy and fuzzy_match(query, release_notes_text)):
                    matched = True
                    if match_type == 'description':
                        match_type = 'description_and_release_notes'
                    elif not match_type:
                        match_type = 'release_notes'
                    if not release_notes_context:
                        release_notes_context = find_match_context(query, indexed_data.get('release_notes_text', ''))
            
            if matched:
                seen_keys.add(addon_key)
                result = {
                    'addon_key': addon_key,
                    'app_name': app.get('name', 'Unknown'),
                    'vendor': app.get('vendor', 'N/A'),
                    'match_type': match_type or 'description',
                    'match_context': match_context or 'Found in description',
                    'products': app.get('products', [])
                }
                
                if release_notes_context:
                    result['release_notes_context'] = release_notes_context
                
                results.append(result)
        
        return results

