"""Search index using Whoosh full-text search library."""

import os
import json
from typing import Dict, List, Optional
from pathlib import Path
from bs4 import BeautifulSoup
from whoosh import index
from whoosh.fields import Schema, TEXT, ID, KEYWORD
from whoosh.qparser import QueryParser, MultifieldParser, OrGroup
from whoosh.query import And, Or, Term, Wildcard
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
    import re
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


class WhooshSearchIndex:
    """Search index using Whoosh full-text search."""
    
    def __init__(self, index_dir: Optional[Path] = None):
        """
        Initialize Whoosh search index.
        
        Args:
            index_dir: Directory for Whoosh index (optional)
        """
        self.index_dir = index_dir or Path(settings.DESCRIPTIONS_DIR) / '.whoosh_index'
        self.index_dir.mkdir(parents=True, exist_ok=True)
        
        # Define schema for search index
        self.schema = Schema(
            addon_key=ID(stored=True, unique=True),
            app_name=TEXT(stored=True),
            vendor=TEXT(stored=True),
            products=KEYWORD(stored=True, commas=True),
            json_text=TEXT,
            html_text=TEXT,
            release_notes_text=TEXT,
            all_text=TEXT  # Combined text for general search
        )
        
        self._index = None
    
    def _get_index(self):
        """Get or create Whoosh index."""
        if self._index is None:
            if index.exists_in(str(self.index_dir)):
                self._index = index.open_dir(str(self.index_dir))
            else:
                self._index = index.create_in(str(self.index_dir), self.schema)
        return self._index
    
    def build_index(self, metadata_store):
        """Build search index from all descriptions and release notes."""
        import sys
        
        # Fix encoding for Windows console (cp1252 doesn't support Unicode)
        if sys.platform == 'win32':
            try:
                # Try to set UTF-8 encoding for stdout/stderr
                if hasattr(sys.stdout, 'reconfigure'):
                    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
                if hasattr(sys.stderr, 'reconfigure'):
                    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                # Fallback: use ASCII-safe output
                pass
        
        logger.info("Building Whoosh search index...")
        print("Building Whoosh search index...")
        sys.stdout.flush()
        
        # Create new index
        if index.exists_in(str(self.index_dir)):
            # Remove old index
            import shutil
            shutil.rmtree(self.index_dir)
            print("Removed old index")
            sys.stdout.flush()
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._index = index.create_in(str(self.index_dir), self.schema)
        
        writer = self._index.writer()
        descriptions_dir = Path(settings.DESCRIPTIONS_DIR)
        
        if not descriptions_dir.exists():
            logger.warning(f"Descriptions directory does not exist: {descriptions_dir}")
            print(f"Warning: Descriptions directory does not exist: {descriptions_dir}")
            sys.stdout.flush()
            writer.commit()
            return 0
        
        # Count total items for progress
        items = [item for item in descriptions_dir.iterdir() if item.is_dir()]
        total_items = len(items)
        
        indexed_count = 0
        processed_count = 0
        
        # Index descriptions from JSON files and HTML
        for item in descriptions_dir.iterdir():
            if not item.is_dir():
                continue
            
            processed_count += 1
            addon_key = item.name.replace('_', '.')
            
            # Print progress
            if processed_count % 10 == 0 or processed_count == total_items:
                progress_pct = (processed_count / total_items * 100) if total_items > 0 else 0
                print(f"Progress: {processed_count}/{total_items} ({progress_pct:.1f}%) - Indexed: {indexed_count}", end='\r')
                sys.stdout.flush()
            
            app = metadata_store.get_app_by_key(addon_key)
            if not app:
                continue
            
            json_text = ''
            html_text = ''
            
            # Index JSON description files
            json_files = list(item.glob('*.json'))
            for json_file in json_files:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        desc_data = json.load(f)
                    
                    # Extract text from various fields
                    text_parts = []
                    
                    # Summary
                    summary = desc_data.get('summary', '')
                    if summary:
                        text_parts.append(strip_html_tags(str(summary)))
                    
                    # Overview
                    overview = desc_data.get('overview', {})
                    if isinstance(overview, dict):
                        for key in ['body', 'text', 'content', 'html']:
                            val = overview.get(key, '')
                            if val:
                                text_parts.append(strip_html_tags(str(val)))
                    elif isinstance(overview, str):
                        text_parts.append(strip_html_tags(overview))
                    
                    # Highlights
                    highlights = desc_data.get('highlights', {})
                    if isinstance(highlights, dict):
                        for key in ['body', 'text', 'content', 'html']:
                            val = highlights.get(key, '')
                            if val:
                                text_parts.append(strip_html_tags(str(val)))
                    elif isinstance(highlights, str):
                        text_parts.append(strip_html_tags(highlights))
                    
                    # Addon info
                    addon = desc_data.get('addon', {})
                    if isinstance(addon, dict):
                        for key in ['summary', 'description']:
                            val = addon.get(key, '')
                            if val:
                                text_parts.append(strip_html_tags(str(val)))
                    
                    if text_parts:
                        json_text = ' '.join(text_parts)
                except Exception as e:
                    logger.debug(f"Error indexing JSON file {json_file}: {str(e)}")
            
            # Index full page HTML files
            full_page_dir = item / 'full_page'
            if full_page_dir.exists():
                html_files = list(full_page_dir.glob('*.html'))
                for html_file in html_files:
                    if html_file.name == 'index.html' or 'index' in html_file.name.lower():
                        try:
                            extracted_text = extract_text_from_html_file(html_file)
                            if extracted_text:
                                if html_text:
                                    html_text += ' ' + extracted_text
                                else:
                                    html_text = extracted_text
                        except Exception as e:
                            logger.debug(f"Error indexing HTML file {html_file}: {str(e)}")
            
            # Index release notes from database
            release_notes_texts = []
            versions = metadata_store.get_app_versions(addon_key)
            for version in versions:
                release_notes = version.get('release_notes', '')
                if release_notes:
                    release_notes_texts.append(strip_html_tags(release_notes))
            
            release_notes_text = ' '.join(release_notes_texts) if release_notes_texts else ''
            
            # Combine all text for general search
            all_text = ' '.join([json_text, html_text, release_notes_text]).strip()
            
            # Only index if there's some content
            if all_text:
                products = app.get('products', [])
                products_str = ','.join(products) if products else ''
                
                writer.add_document(
                    addon_key=addon_key,
                    app_name=app.get('name', 'Unknown'),
                    vendor=app.get('vendor', 'N/A'),
                    products=products_str,
                    json_text=json_text,
                    html_text=html_text,
                    release_notes_text=release_notes_text,
                    all_text=all_text
                )
                indexed_count += 1
        
        writer.commit()
        print()  # New line after progress
        logger.info(f"Built Whoosh search index with {indexed_count} documents")
        print(f"Indexed {indexed_count} plugins successfully")
        sys.stdout.flush()
        
        return indexed_count
    
    def search(self, query: str, metadata_store, limit: int = 100) -> List[Dict]:
        """
        Search in indexed content using Whoosh.
        
        Args:
            query: Search query
            metadata_store: MetadataStore instance (for app info)
            limit: Maximum number of results
        
        Returns:
            List of search results
        """
        if not query or not query.strip():
            return []
        
        try:
            idx = self._get_index()
            
            # Check if index has any documents
            with idx.searcher() as test_searcher:
                doc_count = test_searcher.doc_count()
                if doc_count == 0:
                    logger.warning(f"Whoosh index is empty (0 documents), cannot search")
                    return []
            
            # Use MultifieldParser to search across multiple fields
            # This allows searching in all_text, json_text, html_text, and release_notes_text
            parser = MultifieldParser(
                ["all_text", "json_text", "html_text", "release_notes_text", "app_name", "vendor"],
                schema=idx.schema,
                group=OrGroup  # Use OR for multiple fields (match in any field)
            )
            
            # Parse query - Whoosh supports:
            # - Simple words: "table"
            # - Phrases: "table grid"
            # - Wildcards: "table*"
            # - Boolean: "table AND grid", "table OR grid"
            try:
                parsed_query = parser.parse(query)
            except Exception as parse_error:
                logger.warning(f"Whoosh query parsing failed for '{query}': {str(parse_error)}, trying simple term search")
                # Fallback: try simple term search
                from whoosh.query import Term, Or
                query_terms = query.lower().split()
                if query_terms:
                    term_queries = []
                    for term in query_terms:
                        # Try searching in all_text field
                        term_queries.append(Term("all_text", term))
                    parsed_query = Or(term_queries) if len(term_queries) > 1 else term_queries[0]
                else:
                    return []
            
            with idx.searcher() as searcher:
                results_list = searcher.search(parsed_query, limit=limit)
                logger.debug(f"Whoosh search for '{query}' returned {len(results_list)} results")
                
                results = []
                for hit in results_list:
                    try:
                        addon_key = hit.get('addon_key')
                        if not addon_key:
                            continue
                        
                        app = metadata_store.get_app_by_key(addon_key)
                        if not app:
                            logger.debug(f"App not found for addon_key: {addon_key}")
                            continue
                        
                        # Determine match type based on which fields matched
                        match_type = 'description'
                        match_context = ''
                        release_notes_context = ''
                        
                        # Check which fields have content
                        json_text = hit.get('json_text', '') or ''
                        html_text = hit.get('html_text', '') or ''
                        release_notes_text = hit.get('release_notes_text', '') or ''
                        
                        # Try to extract context from matched fields
                        # Whoosh highlights are available via hit.highlights()
                        try:
                            highlights = hit.highlights('all_text', top=1)
                            if highlights:
                                match_context = highlights
                        except Exception:
                            pass
                        
                        if not match_context:
                            # Try highlights from other fields
                            for field in ['json_text', 'html_text', 'release_notes_text']:
                                try:
                                    highlights = hit.highlights(field, top=1)
                                    if highlights:
                                        match_context = highlights
                                        break
                                except Exception:
                                    pass
                        
                        # Fallback to text snippets
                        if not match_context:
                            if json_text:
                                match_context = json_text[:300] + '...' if len(json_text) > 300 else json_text
                            elif html_text:
                                match_context = html_text[:300] + '...' if len(html_text) > 300 else html_text
                        
                        if release_notes_text:
                            release_notes_context = release_notes_text[:300] + '...' if len(release_notes_text) > 300 else release_notes_text
                            if match_type == 'description':
                                match_type = 'description_and_release_notes'
                            elif not json_text and not html_text:
                                match_type = 'release_notes'
                        
                        result = {
                            'addon_key': addon_key,
                            'app_name': hit.get('app_name') or app.get('name', 'Unknown'),
                            'vendor': hit.get('vendor') or app.get('vendor', 'N/A'),
                            'match_type': match_type,
                            'match_context': match_context or 'Found in description',
                            'products': app.get('products', []),
                            'score': hit.score  # Relevance score from Whoosh
                        }
                        
                        if release_notes_context:
                            result['release_notes_context'] = release_notes_context
                        
                        results.append(result)
                    except Exception as hit_error:
                        logger.warning(f"Error processing search hit: {str(hit_error)}")
                        continue
                
                # Sort by relevance score (highest first)
                results.sort(key=lambda x: x.get('score', 0), reverse=True)
                
                logger.debug(f"Whoosh search completed, returning {len(results)} results")
                return results
                
        except Exception as e:
            logger.error(f"Error in Whoosh search: {str(e)}", exc_info=True)
            return []
    
    def needs_rebuild(self) -> bool:
        """Check if index needs to be rebuilt."""
        return not index.exists_in(str(self.index_dir))

