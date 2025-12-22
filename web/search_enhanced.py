"""Enhanced search that searches across all local data sources."""

import os
import json
import re
from typing import Dict, List, Optional
from pathlib import Path
from bs4 import BeautifulSoup
from config import settings
from utils.logger import get_logger

logger = get_logger('web')


def strip_html_tags(html_text: str) -> str:
    """Remove HTML tags from text."""
    if not html_text:
        return ''
    
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


class EnhancedSearch:
    """Enhanced search that searches across all local data sources."""
    
    def __init__(self):
        """Initialize enhanced search."""
        self.descriptions_dir = Path(settings.DESCRIPTIONS_DIR)
        self.metadata_store = None  # Will be set when needed
    
    def search_all(self, query: str, metadata_store, limit: int = 100) -> List[Dict]:
        """
        Search across all local data sources:
        - App names, vendors, addon keys
        - JSON descriptions
        - HTML descriptions
        - Release notes
        - App metadata (categories, products, etc.)
        
        Args:
            query: Search query
            metadata_store: MetadataStore instance
            limit: Maximum number of results
            
        Returns:
            List of search results with relevance scores
        """
        if not query or not query.strip():
            return []
        
        self.metadata_store = metadata_store
        query_lower = query.lower().strip()
        query_words = query_lower.split()
        
        results = {}
        
        # 1. Search in app metadata (names, vendors, keys, categories)
        apps = metadata_store.get_all_apps()
        for app in apps:
            addon_key = app.get('addon_key', '')
            if not addon_key:
                continue
            
            score = 0
            match_reasons = []
            
            # Check app name
            app_name = (app.get('name') or '').lower()
            if query_lower in app_name:
                score += 10
                match_reasons.append('name')
            elif any(word in app_name for word in query_words):
                score += 5
                match_reasons.append('name')
            
            # Check vendor
            vendor = (app.get('vendor') or '').lower()
            if query_lower in vendor:
                score += 8
                match_reasons.append('vendor')
            elif any(word in vendor for word in query_words):
                score += 4
                match_reasons.append('vendor')
            
            # Check addon key
            if query_lower in addon_key.lower():
                score += 6
                match_reasons.append('key')
            
            # Check categories
            categories = [c.lower() for c in (app.get('categories') or [])]
            for cat in categories:
                if query_lower in cat or any(word in cat for word in query_words):
                    score += 3
                    match_reasons.append('category')
            
            # Check products
            products = [p.lower() for p in (app.get('products') or [])]
            for prod in products:
                if query_lower in prod or any(word in prod for word in query_words):
                    score += 2
                    match_reasons.append('product')
            
            if score > 0:
                results[addon_key] = {
                    'addon_key': addon_key,
                    'app_name': app.get('name', 'Unknown'),
                    'vendor': app.get('vendor', 'N/A'),
                    'products': app.get('products', []),
                    'score': score,
                    'match_type': 'metadata',
                    'match_context': f"Matched in: {', '.join(set(match_reasons))}",
                    'match_reasons': match_reasons
                }
        
        # 2. Search in descriptions (JSON and HTML)
        if self.descriptions_dir.exists():
            for item in self.descriptions_dir.iterdir():
                if not item.is_dir():
                    continue
                
                addon_key = item.name.replace('_', '.')
                
                # Skip if already found with high score
                if addon_key in results and results[addon_key]['score'] >= 10:
                    continue
                
                # Search in JSON files
                json_files = list(item.glob('*.json'))
                json_text = ''
                for json_file in json_files:
                    try:
                        with open(json_file, 'r', encoding='utf-8', errors='replace') as f:
                            json_data = json.load(f)
                        
                        # Extract text from various fields
                        text_parts = []
                        
                        # Summary
                        summary = json_data.get('summary', '')
                        if summary:
                            text_parts.append(strip_html_tags(str(summary)))
                        
                        # Overview
                        overview = json_data.get('overview', {})
                        if isinstance(overview, dict):
                            for key in ['body', 'text', 'content', 'html']:
                                val = overview.get(key, '')
                                if val:
                                    text_parts.append(strip_html_tags(str(val)))
                        elif isinstance(overview, str):
                            text_parts.append(strip_html_tags(overview))
                        
                        # Highlights
                        highlights = json_data.get('highlights', {})
                        if isinstance(highlights, dict):
                            for key in ['body', 'text', 'content', 'html']:
                                val = highlights.get(key, '')
                                if val:
                                    text_parts.append(strip_html_tags(str(val)))
                        elif isinstance(highlights, str):
                            text_parts.append(strip_html_tags(highlights))
                        
                        # Addon info
                        addon = json_data.get('addon', {})
                        if isinstance(addon, dict):
                            for key in ['summary', 'description']:
                                val = addon.get(key, '')
                                if val:
                                    text_parts.append(strip_html_tags(str(val)))
                        
                        if text_parts:
                            json_text = ' '.join(text_parts)
                    except Exception as e:
                        logger.debug(f"Error reading JSON {json_file}: {str(e)}")
                
                # Search in HTML files
                html_text = ''
                full_page_dir = item / 'full_page'
                if full_page_dir.exists():
                    html_files = list(full_page_dir.glob('*.html'))
                    for html_file in html_files:
                        if html_file.name == 'index.html' or 'index' in html_file.name.lower():
                            try:
                                html_text = extract_text_from_html_file(html_file)
                                break
                            except Exception:
                                pass
                
                # Combine texts
                combined_text = (json_text + ' ' + html_text).lower()
                
                # Calculate match score
                text_score = 0
                match_context = ''
                match_type = 'description'
                
                if combined_text:
                    # Exact phrase match
                    if query_lower in combined_text:
                        text_score = 7
                        # Find context around match
                        idx = combined_text.find(query_lower)
                        start = max(0, idx - 150)
                        end = min(len(combined_text), idx + len(query_lower) + 150)
                        match_context = combined_text[start:end].strip()
                        if start > 0:
                            match_context = '...' + match_context
                        if end < len(combined_text):
                            match_context = match_context + '...'
                    # Word matches
                    elif any(word in combined_text for word in query_words):
                        text_score = 4
                        # Find context around first match
                        for word in query_words:
                            if word in combined_text:
                                idx = combined_text.find(word)
                                start = max(0, idx - 150)
                                end = min(len(combined_text), idx + len(word) + 150)
                                match_context = combined_text[start:end].strip()
                                if start > 0:
                                    match_context = '...' + match_context
                                if end < len(combined_text):
                                    match_context = match_context + '...'
                                break
                
                # Search in release notes
                release_notes_text = ''
                release_notes_score = 0
                versions = metadata_store.get_app_versions(addon_key)
                for version in versions:
                    release_notes = version.get('release_notes', '')
                    if release_notes:
                        release_notes_clean = strip_html_tags(release_notes).lower()
                        release_notes_text += ' ' + release_notes_clean
                        
                        if query_lower in release_notes_clean:
                            release_notes_score = 6
                        elif any(word in release_notes_clean for word in query_words):
                            release_notes_score = 3
                
                # Update score
                total_score = text_score + release_notes_score
                if total_score > 0:
                    if addon_key in results:
                        results[addon_key]['score'] += total_score
                        if text_score > 0:
                            results[addon_key]['match_type'] = 'description_and_release_notes' if release_notes_score > 0 else 'description'
                            results[addon_key]['match_context'] = match_context or results[addon_key].get('match_context', '')
                        if release_notes_score > 0:
                            results[addon_key]['release_notes_context'] = release_notes_text[:300] + '...' if len(release_notes_text) > 300 else release_notes_text
                    else:
                        # Get app info
                        app = metadata_store.get_app_by_key(addon_key)
                        if app:
                            results[addon_key] = {
                                'addon_key': addon_key,
                                'app_name': app.get('name', 'Unknown'),
                                'vendor': app.get('vendor', 'N/A'),
                                'products': app.get('products', []),
                                'score': total_score,
                                'match_type': 'description_and_release_notes' if release_notes_score > 0 else 'description',
                                'match_context': match_context or 'Found in description',
                                'release_notes_context': release_notes_text[:300] + '...' if release_notes_score > 0 and len(release_notes_text) > 300 else (release_notes_text if release_notes_score > 0 else None)
                            }
        
        # Sort by score (highest first) and limit results
        sorted_results = sorted(results.values(), key=lambda x: x['score'], reverse=True)
        return sorted_results[:limit]

