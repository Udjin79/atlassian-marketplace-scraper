"""Flask routes for the web interface."""

import os
import re
from flask import render_template, jsonify, request, send_file, redirect, url_for
from config import settings
from config.products import PRODUCTS, PRODUCT_LIST
from scraper.metadata_store import MetadataStore
from scraper.download_manager import DownloadManager
from utils.logger import get_logger
from utils.task_manager import get_task_manager
from utils.settings_manager import read_env_settings, update_env_setting
from utils.auth import requires_auth

logger = get_logger('web')


def register_routes(app):
    """Register all Flask routes."""

    store = MetadataStore()
    download_mgr = DownloadManager()

    @app.route('/')
    def index():
        """Dashboard homepage."""
        try:
            # Get statistics
            total_apps = store.get_apps_count()
            total_versions = store.get_total_versions_count()
            downloaded_versions = store.get_downloaded_versions_count()
            storage_stats = download_mgr.get_storage_stats()
            
            # Get detailed storage stats only if requested (lazy loading)
            # This avoids slow page loads - detailed stats will be loaded via AJAX
            include_detailed = request.args.get('detailed', 'false').lower() == 'true'
            detailed_stats = None
            if include_detailed:
                detailed_stats = download_mgr.get_detailed_storage_stats()

            stats = {
                'total_apps': total_apps,
                'total_versions': total_versions,
                'downloaded_versions': downloaded_versions,
                'pending_downloads': total_versions - downloaded_versions,
                'storage_used_gb': storage_stats.get('total_gb', 0),
                'storage_used_mb': storage_stats.get('total_mb', 0),
                'file_count': storage_stats.get('file_count', 0),
                'detailed_storage': detailed_stats
            }

            return render_template('index.html', stats=stats, products=PRODUCTS)

        except Exception as e:
            logger.error(f"Error loading dashboard: {str(e)}")
            return render_template('error.html', error=str(e)), 500

    @app.route('/apps')
    def apps_list():
        """List all apps with filtering and pagination."""
        try:
            # Get filters from query parameters
            product_filter = request.args.get('product')
            search_query = request.args.get('search', '').strip()
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 50))

            # Build filters
            filters = {}
            if product_filter:
                filters['product'] = product_filter
            if search_query:
                filters['search'] = search_query

            # Get total count for pagination (with filters applied)
            total_apps = store.get_apps_count(filters)
            total_pages = (total_apps + per_page - 1) // per_page

            # Get paginated apps directly from database
            start_idx = (page - 1) * per_page
            apps = store.get_all_apps(filters, limit=per_page, offset=start_idx)

            return render_template(
                'apps_list.html',
                apps=apps,
                products=PRODUCTS,
                product_list=PRODUCT_LIST,
                current_product=product_filter,
                search_query=search_query,
                page=page,
                per_page=per_page,
                total_apps=total_apps,
                total_pages=total_pages
            )

        except Exception as e:
            logger.error(f"Error loading apps list: {str(e)}")
            return render_template('error.html', error=str(e)), 500

    @app.route('/apps/<addon_key>')
    def app_detail(addon_key):
        """Show detailed information about a specific app."""
        try:
            # Get app
            app = store.get_app_by_key(addon_key)
            if not app:
                return render_template('error.html', error=f"App not found: {addon_key}"), 404

            # Get versions
            versions = store.get_app_versions(addon_key)

            # Sort versions by release date (newest first)
            versions = sorted(
                versions,
                key=lambda v: v.get('release_date', ''),
                reverse=True
            )

            # Check if description exists
            description_dir = os.path.join(settings.DESCRIPTIONS_DIR, addon_key.replace('.', '_'))
            description_files = []
            full_page_path = None
            api_overview = None  # Brief description from API
            
            if os.path.exists(description_dir):
                # Check for full page first
                full_page_dir = os.path.join(description_dir, 'full_page')
                if os.path.exists(full_page_dir):
                    full_page_index = os.path.join(full_page_dir, 'index.html')
                    if os.path.exists(full_page_index):
                        full_page_path = 'full_page/index.html'
                
                # Also list API-based descriptions
                for file in os.listdir(description_dir):
                    if file.endswith('.html') and file != 'index.html':
                        description_files.append(file)
                
                # Try to load overview from latest JSON description
                json_files = [f for f in os.listdir(description_dir) if f.endswith('.json')]
                if json_files:
                    # Get latest JSON file
                    latest_json = sorted(json_files)[-1]
                    json_path = os.path.join(description_dir, latest_json)
                    try:
                        import json
                        with open(json_path, 'r', encoding='utf-8') as f:
                            desc_data = json.load(f)
                            # Extract overview text
                            overview = desc_data.get('overview', {})
                            if isinstance(overview, dict):
                                # Try different possible keys
                                api_overview = (
                                    overview.get('body', '') or 
                                    overview.get('text', '') or 
                                    overview.get('content', '') or
                                    str(overview.get('html', ''))[:500] if overview.get('html') else ''
                                )
                            elif isinstance(overview, str):
                                api_overview = overview
                    except Exception as e:
                        logger.debug(f"Could not load overview from JSON: {str(e)}")

            return render_template(
                'app_detail.html',
                app=app,
                versions=versions,
                description_files=description_files,
                description_dir=description_dir,
                full_page_path=full_page_path,
                api_overview=api_overview
            )

        except Exception as e:
            logger.error(f"Error loading app details for {addon_key}: {str(e)}")
            return render_template('error.html', error=str(e)), 500

    @app.route('/apps/<addon_key>/description/assets/<path:asset_path>')
    def app_description_asset(addon_key, asset_path):
        """Serve assets for description pages."""
        try:
            # Security: Validate addon_key to prevent path traversal
            if '..' in addon_key or '/' in addon_key or '\\' in addon_key:
                return render_template('error.html', error="Invalid addon key"), 400

            # Security: Validate asset_path doesn't contain path traversal
            if '..' in asset_path:
                logger.warning(f"Path traversal attempt in assets: {asset_path}")
                return render_template('error.html', error="Invalid path"), 400

            # Only allow safe file extensions for assets
            allowed_extensions = ('.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.woff', '.woff2', '.ttf', '.eot', '.ico')
            if not any(asset_path.lower().endswith(ext) for ext in allowed_extensions):
                return render_template('error.html', error="File type not allowed"), 400

            asset_file = os.path.join(
                settings.DESCRIPTIONS_DIR,
                addon_key.replace('.', '_'),
                'full_page',
                'assets',
                asset_path
            )

            # Security: Verify resolved path is within expected directory
            base_dir = os.path.realpath(os.path.join(
                settings.DESCRIPTIONS_DIR,
                addon_key.replace('.', '_'),
                'full_page',
                'assets'
            ))
            real_path = os.path.realpath(asset_file)

            if not real_path.startswith(base_dir):
                logger.warning(f"Path traversal attempt detected in assets: {asset_path} -> {real_path}")
                return render_template('error.html', error="Access denied"), 403

            if os.path.exists(asset_file) and os.path.isfile(asset_file):
                return send_file(asset_file)
            else:
                return render_template('error.html', error="Asset not found"), 404
        except Exception as e:
            logger.error(f"Error serving asset {addon_key}/{asset_path}: {str(e)}")
            return render_template('error.html', error=str(e)), 500

    @app.route('/apps/<addon_key>/description/<path:filename>')
    def app_description(addon_key, filename):
        """Show downloaded description page."""
        try:
            # Security: Validate addon_key to prevent path traversal
            if '..' in addon_key or '/' in addon_key or '\\' in addon_key:
                return render_template('error.html', error="Invalid addon key"), 400

            # Handle full_page/index.html path
            if filename.startswith('full_page/'):
                filename = filename.replace('full_page/', '', 1)

                # Security: Validate filename doesn't contain path separators after removal
                if '..' in filename or '/' in filename or '\\' in filename:
                    return render_template('error.html', error="Invalid filename"), 400

                # Only allow safe file extensions
                allowed_extensions = ('.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.woff', '.woff2', '.ttf', '.eot')
                if not any(filename.lower().endswith(ext) for ext in allowed_extensions):
                    return render_template('error.html', error="File type not allowed"), 400

                description_path = os.path.join(
                    settings.DESCRIPTIONS_DIR,
                    addon_key.replace('.', '_'),
                    'full_page',
                    filename
                )

                # Security: Verify resolved path is within expected directory
                base_dir = os.path.realpath(os.path.join(
                    settings.DESCRIPTIONS_DIR,
                    addon_key.replace('.', '_'),
                    'full_page'
                ))
                real_path = os.path.realpath(description_path)

                if not real_path.startswith(base_dir):
                    logger.warning(f"Path traversal attempt detected: {filename} -> {real_path}")
                    return render_template('error.html', error="Access denied"), 403
            else:
                # Security: sanitize filename (remove any path components)
                filename = os.path.basename(filename)

                # Allow only .html files
                if not filename.endswith('.html') and filename != 'index.html':
                    return render_template('error.html', error="Invalid file type"), 400

                description_path = os.path.join(
                    settings.DESCRIPTIONS_DIR,
                    addon_key.replace('.', '_'),
                    filename
                )

                # Security: Verify resolved path is within expected directory
                base_dir = os.path.realpath(os.path.join(
                    settings.DESCRIPTIONS_DIR,
                    addon_key.replace('.', '_')
                ))
                real_path = os.path.realpath(description_path)

                if not real_path.startswith(base_dir):
                    logger.warning(f"Path traversal attempt detected: {filename} -> {real_path}")
                    return render_template('error.html', error="Access denied"), 403
                
                # Also check full_page directory
                if not os.path.exists(description_path):
                    full_page_path = os.path.join(
                        settings.DESCRIPTIONS_DIR,
                        addon_key.replace('.', '_'),
                        'full_page',
                        filename
                    )
                    if os.path.exists(full_page_path):
                        description_path = full_page_path
                    else:
                        return render_template('error.html', error="Description not found"), 404
                elif filename == 'index.html':
                    # Check if it's in full_page directory
                    full_page_path = os.path.join(
                        settings.DESCRIPTIONS_DIR,
                        addon_key.replace('.', '_'),
                        'full_page',
                        'index.html'
                    )
                    if os.path.exists(full_page_path):
                        description_path = full_page_path
            
            # Check if file exists
            if not os.path.exists(description_path):
                return render_template('error.html', error="Description not found"), 404

            # For full page, serve assets as well
            if 'full_page' in description_path:
                # Check if it's an asset request
                if filename != 'index.html':
                    # Serve asset file
                    return send_file(description_path)
                
                # Read and return HTML content
                try:
                    # Read as binary first to handle encoding issues
                    with open(description_path, 'rb') as f:
                        raw_bytes = f.read()
                    
                    # Try UTF-8 first
                    try:
                        html_content = raw_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        # If UTF-8 fails, try latin-1 and convert to UTF-8
                        html_content = raw_bytes.decode('latin-1', errors='replace')
                        # Re-encode to UTF-8
                        html_content = html_content.encode('utf-8', errors='replace').decode('utf-8')
                except Exception as e:
                    logger.error(f"Error reading HTML file {description_path}: {str(e)}")
                    return render_template('error.html', error=f"Error reading description: {str(e)}"), 500

                # Ensure DOCTYPE is present (prevents Quirks Mode)
                if not html_content.strip().startswith('<!DOCTYPE'):
                    html_content = '<!DOCTYPE html>\n' + html_content

                # Ensure charset meta tag exists
                if '<meta charset' not in html_content.lower() and '<meta http-equiv="content-type"' not in html_content.lower():
                    # Insert charset meta tag in head
                    if '<head>' in html_content:
                        html_content = html_content.replace('<head>', '<head>\n    <meta charset="UTF-8">')
                    elif '<html' in html_content:
                        # Insert after html tag
                        html_content = re.sub(r'(<html[^>]*>)', r'\1\n<head>\n    <meta charset="UTF-8">\n</head>', html_content, count=1)

                # Inject navigation back to app detail
                nav_html = f'''
                <div style="background: #fff; padding: 1rem; margin-bottom: 1rem; border-bottom: 2px solid #0f5ef7; position: sticky; top: 0; z-index: 1000;">
                    <a href="/apps/{addon_key}" style="color: #0f5ef7; text-decoration: none; font-weight: bold;">
                        ← Back to App Details
                    </a>
                </div>
                '''

                # Insert navigation after body tag
                html_content = html_content.replace('<body>', '<body>' + nav_html)
                
                # Fix asset paths to use Flask routes
                # Replace local asset paths with Flask routes
                html_content = re.sub(
                    r'(src|href)=["\']assets/([^"\']+)["\']',
                    lambda m: f'{m.group(1)}="/apps/{addon_key}/description/assets/{m.group(2)}"',
                    html_content
                )
                # Also handle relative paths
                html_content = re.sub(
                    r'(src|href)=["\'](?!https?://|/|#|javascript:|data:)([^"\']+)["\']',
                    lambda m: f'{m.group(1)}="/apps/{addon_key}/description/assets/{m.group(2)}"',
                    html_content
                )

                # Return with proper Content-Type header
                from flask import Response
                return Response(html_content, mimetype='text/html; charset=utf-8')
            else:
                # API-based description
                try:
                    with open(description_path, 'r', encoding='utf-8', errors='replace') as f:
                        html_content = f.read()
                except UnicodeDecodeError:
                    # Try with different encoding if UTF-8 fails
                    with open(description_path, 'r', encoding='latin-1', errors='replace') as f:
                        html_content = f.read()
                    # Convert to UTF-8
                    html_content = html_content.encode('utf-8', errors='replace').decode('utf-8')

                # Ensure charset meta tag exists
                if '<meta charset' not in html_content.lower() and '<meta http-equiv="content-type"' not in html_content.lower():
                    # Insert charset meta tag in head
                    if '<head>' in html_content:
                        html_content = html_content.replace('<head>', '<head>\n    <meta charset="UTF-8">')
                    elif '<html' in html_content:
                        # Insert after html tag
                        html_content = re.sub(r'(<html[^>]*>)', r'\1\n<head>\n    <meta charset="UTF-8">\n</head>', html_content, count=1)

                # Inject navigation back to app detail
                nav_html = f'''
                <div style="background: #fff; padding: 1rem; margin-bottom: 1rem; border-bottom: 2px solid #0f5ef7;">
                    <a href="/apps/{addon_key}" style="color: #0f5ef7; text-decoration: none;">
                        ← Back to App Details
                    </a>
                </div>
                '''

                # Insert navigation after body tag
                html_content = html_content.replace('<body>', '<body>' + nav_html)

                # Return with proper Content-Type header
                from flask import Response
                return Response(html_content, mimetype='text/html; charset=utf-8')

        except Exception as e:
            logger.error(f"Error loading description for {addon_key}/{filename}: {str(e)}")
            return render_template('error.html', error=str(e)), 500

    @app.route('/descriptions')
    def descriptions_list():
        """List all apps with descriptions."""
        try:
            descriptions_dir = settings.DESCRIPTIONS_DIR
            apps_with_descriptions = []

            if os.path.exists(descriptions_dir):
                for item in os.listdir(descriptions_dir):
                    item_path = os.path.join(descriptions_dir, item)
                    if os.path.isdir(item_path):
                        # Convert back from sanitized name
                        addon_key = item.replace('_', '.')
                        app = store.get_app_by_key(addon_key)
                        if app:
                            # Find all HTML files (including in subdirectories like full_page)
                            html_files = []
                            
                            # Check root directory
                            for f in os.listdir(item_path):
                                if f.endswith('.html'):
                                    html_files.append(f)
                            
                            # Check full_page subdirectory
                            full_page_dir = os.path.join(item_path, 'full_page')
                            if os.path.exists(full_page_dir):
                                for f in os.listdir(full_page_dir):
                                    if f.endswith('.html'):
                                        # Store with path for full_page
                                        html_files.append(f'full_page/{f}')
                            
                            # Check for JSON files (API descriptions)
                            json_files = [f for f in os.listdir(item_path) if f.endswith('.json')]
                            
                            if html_files or json_files:
                                # Determine latest description
                                latest_description = None
                                if html_files:
                                    # Prefer full_page/index.html if exists
                                    if 'full_page/index.html' in html_files:
                                        latest_description = 'full_page/index.html'
                                    else:
                                        latest_description = sorted(html_files)[-1]
                                
                                # Extract documentation URL from JSON files
                                documentation_url = None
                                if json_files:
                                    # Try to find documentation URL in the latest JSON file
                                    try:
                                        import json
                                        latest_json = sorted(json_files)[-1]
                                        json_path = os.path.join(item_path, latest_json)
                                        with open(json_path, 'r', encoding='utf-8') as f:
                                            json_data = json.load(f)
                                            documentation_url = json_data.get('documentation_url') or json_data.get('addon', {}).get('vendorLinks', {}).get('Documentation')
                                    except Exception:
                                        pass
                                
                                apps_with_descriptions.append({
                                    'app': app,
                                    'addon_key': addon_key,
                                    'description_count': len(html_files),
                                    'json_count': len(json_files),
                                    'latest_description': latest_description,
                                    'has_full_page': 'full_page/index.html' in html_files if html_files else False,
                                    'documentation_url': documentation_url
                                })

            return render_template(
                'descriptions_list.html',
                apps=apps_with_descriptions
            )

        except Exception as e:
            logger.error(f"Error loading descriptions list: {str(e)}")
            return render_template('error.html', error=str(e)), 500

    @app.route('/download/<product>/<addon_key>/<version_id>')
    def download_binary(product, addon_key, version_id):
        """Download a binary file."""
        try:
            # Find the file using product-specific storage
            product_binaries_dir = settings.get_binaries_dir_for_product(product)
            binary_dir = os.path.join(product_binaries_dir, addon_key, version_id)

            if not os.path.exists(binary_dir):
                return jsonify({'error': 'Binary not found'}), 404

            # Find JAR/OBR file in directory
            files = os.listdir(binary_dir)
            binary_file = None

            for file in files:
                if file.endswith(('.jar', '.obr')):
                    binary_file = file
                    break

            if not binary_file:
                return jsonify({'error': 'Binary file not found in directory'}), 404

            file_path = os.path.join(binary_dir, binary_file)

            return send_file(
                file_path,
                as_attachment=True,
                download_name=binary_file
            )

        except Exception as e:
            logger.error(f"Error downloading binary: {str(e)}")
            return jsonify({'error': str(e)}), 500

    # API Routes

    @app.route('/api/apps')
    def api_apps():
        """Get apps list as JSON."""
        try:
            product_filter = request.args.get('product')
            search_query = request.args.get('search', '').strip()

            filters = {}
            if product_filter:
                filters['product'] = product_filter
            if search_query:
                filters['search'] = search_query

            apps = store.get_all_apps(filters)

            return jsonify({
                'success': True,
                'count': len(apps),
                'apps': apps
            })

        except Exception as e:
            logger.error(f"API error: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/apps/<addon_key>')
    def api_app_detail(addon_key):
        """Get app details as JSON."""
        try:
            app = store.get_app_by_key(addon_key)
            if not app:
                return jsonify({'success': False, 'error': 'App not found'}), 404

            versions = store.get_app_versions(addon_key)

            return jsonify({
                'success': True,
                'app': app,
                'versions': versions
            })

        except Exception as e:
            logger.error(f"API error: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/storage-stats')
    def api_storage_stats():
        """Get detailed storage statistics with breakdown by category, disk, and folders."""
        try:
            detailed_stats = download_mgr.get_detailed_storage_stats()
            return jsonify(detailed_stats)
        except Exception as e:
            logger.error(f"Error getting storage stats: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/storage')
    def storage_details():
        """Storage details page with breakdown by categories and folders."""
        try:
            detailed_stats = download_mgr.get_detailed_storage_stats()
            return render_template('storage_details.html', stats=detailed_stats)
        except Exception as e:
            logger.error(f"Error loading storage details: {str(e)}")
            return render_template('error.html', error=str(e)), 500

    @app.route('/api/stats')
    def api_stats():
        """Get statistics as JSON."""
        try:
            total_apps = store.get_apps_count()
            total_versions = store.get_total_versions_count()
            downloaded = store.get_downloaded_versions_count()
            storage = download_mgr.get_storage_stats()

            return jsonify({
                'success': True,
                'stats': {
                    'total_apps': total_apps,
                    'total_versions': total_versions,
                    'downloaded_versions': downloaded,
                    'pending_downloads': total_versions - downloaded,
                    'storage': storage
                }
            })

        except Exception as e:
            logger.error(f"API error: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/products')
    def api_products():
        """Get product list as JSON."""
        return jsonify({
            'success': True,
            'products': PRODUCTS
        })

    # Management Routes
    
    @app.route('/manage')
    @requires_auth
    def manage():
        """Management page for tasks and settings."""
        try:
            task_mgr = get_task_manager()
            latest_tasks = {
                'pipeline': task_mgr.get_latest_task('pipeline'),
                'scrape_apps': task_mgr.get_latest_task('scrape_apps'),
                'scrape_versions': task_mgr.get_latest_task('scrape_versions'),
                'download': task_mgr.get_latest_task('download'),
                'download_descriptions': task_mgr.get_latest_task('download_descriptions')
            }
            
            # Get current settings (from .env if available, otherwise from settings)
            env_settings = read_env_settings()
            current_settings = {
                'SCRAPER_BATCH_SIZE': env_settings.get('SCRAPER_BATCH_SIZE', str(settings.SCRAPER_BATCH_SIZE)),
                'SCRAPER_REQUEST_DELAY': env_settings.get('SCRAPER_REQUEST_DELAY', str(settings.SCRAPER_REQUEST_DELAY)),
                'VERSION_AGE_LIMIT_DAYS': env_settings.get('VERSION_AGE_LIMIT_DAYS', str(settings.VERSION_AGE_LIMIT_DAYS)),
                'MAX_CONCURRENT_DOWNLOADS': env_settings.get('MAX_CONCURRENT_DOWNLOADS', str(settings.MAX_CONCURRENT_DOWNLOADS)),
                'MAX_VERSION_SCRAPER_WORKERS': env_settings.get('MAX_VERSION_SCRAPER_WORKERS', str(settings.MAX_VERSION_SCRAPER_WORKERS)),
                'MAX_RETRY_ATTEMPTS': env_settings.get('MAX_RETRY_ATTEMPTS', str(settings.MAX_RETRY_ATTEMPTS)),
            }
            
            # Get storage paths
            storage_paths = {
                'METADATA_DIR': env_settings.get('METADATA_DIR', settings.METADATA_DIR),
                'DATABASE_PATH': env_settings.get('DATABASE_PATH', settings.DATABASE_PATH),
                'DESCRIPTIONS_DIR': env_settings.get('DESCRIPTIONS_DIR', settings.DESCRIPTIONS_DIR),
                'LOGS_DIR': env_settings.get('LOGS_DIR', settings.LOGS_DIR),
                'BINARIES_BASE_DIR': env_settings.get('BINARIES_BASE_DIR', settings.BINARIES_BASE_DIR),
                'BINARIES_DIR_JIRA': env_settings.get('BINARIES_DIR_JIRA', settings.PRODUCT_STORAGE_MAP.get('jira', '')),
                'BINARIES_DIR_CONFLUENCE': env_settings.get('BINARIES_DIR_CONFLUENCE', settings.PRODUCT_STORAGE_MAP.get('confluence', '')),
                'BINARIES_DIR_BITBUCKET': env_settings.get('BINARIES_DIR_BITBUCKET', settings.PRODUCT_STORAGE_MAP.get('bitbucket', '')),
                'BINARIES_DIR_BAMBOO': env_settings.get('BINARIES_DIR_BAMBOO', settings.PRODUCT_STORAGE_MAP.get('bamboo', '')),
                'BINARIES_DIR_CROWD': env_settings.get('BINARIES_DIR_CROWD', settings.PRODUCT_STORAGE_MAP.get('crowd', '')),
            }
            
            # Get credentials (without exposing actual values)
            from utils.credentials import get_credentials
            credentials = get_credentials()
            credentials_display = {
                'username': credentials.get('username', ''),
                'api_token': '***' if credentials.get('api_token') else ''
            }
            
            return render_template(
                'manage.html',
                latest_tasks=latest_tasks,
                current_settings=current_settings,
                storage_paths=storage_paths,
                credentials=credentials_display,
                products=PRODUCT_LIST
            )
        except Exception as e:
            logger.error(f"Error loading management page: {str(e)}")
            return render_template('error.html', error=str(e)), 500

    @app.route('/api/tasks/start/scrape-apps', methods=['POST'])
    @requires_auth
    def api_start_scrape_apps():
        """Start app scraping task."""
        try:
            data = request.get_json() or {}
            resume = data.get('resume', False)
            
            task_mgr = get_task_manager()
            task_id = task_mgr.start_scrape_apps(resume=resume)
            
            return jsonify({
                'success': True,
                'task_id': task_id,
                'message': 'App scraping started'
            })
        except Exception as e:
            logger.error(f"Error starting scrape apps: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/tasks/start/scrape-versions', methods=['POST'])
    @requires_auth
    def api_start_scrape_versions():
        """Start version scraping task."""
        try:
            task_mgr = get_task_manager()
            task_id = task_mgr.start_scrape_versions()
            
            return jsonify({
                'success': True,
                'task_id': task_id,
                'message': 'Version scraping started'
            })
        except Exception as e:
            logger.error(f"Error starting scrape versions: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/tasks/start/download', methods=['POST'])
    @requires_auth
    def api_start_download():
        """Start binary download task."""
        try:
            data = request.get_json() or {}
            product = data.get('product')
            
            task_mgr = get_task_manager()
            task_id = task_mgr.start_download_binaries(product=product)
            
            return jsonify({
                'success': True,
                'task_id': task_id,
                'message': 'Binary download started'
            })
        except Exception as e:
            logger.error(f"Error starting download: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/tasks/start/download-descriptions', methods=['POST'])
    @requires_auth
    def api_start_download_descriptions():
        """Start description download task."""
        try:
            data = request.get_json() or {}
            addon_key = data.get('addon_key')
            download_media = data.get('download_media', True)
            
            task_mgr = get_task_manager()
            task_id = task_mgr.start_download_descriptions(addon_key=addon_key, download_media=download_media)
            
            return jsonify({
                'success': True,
                'task_id': task_id,
                'message': 'Description download started'
            })
        except Exception as e:
            logger.error(f"Error starting description download: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/tasks/start/pipeline', methods=['POST'])
    @requires_auth
    def api_start_pipeline():
        """Start full pipeline: scrape apps → versions → binaries → descriptions."""
        try:
            data = request.get_json() or {}
            resume_scrape = data.get('resume_scrape', False)
            download_product = data.get('download_product')
            download_media = data.get('download_media', True)
            
            task_mgr = get_task_manager()
            task_id = task_mgr.start_full_pipeline(
                resume_scrape=resume_scrape,
                download_product=download_product,
                download_media=download_media
            )
            
            return jsonify({
                'success': True,
                'task_id': task_id,
                'message': 'Full pipeline started - all tasks will run sequentially'
            })
        except Exception as e:
            logger.error(f"Error starting pipeline: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/tasks/<task_id>')
    def api_task_status(task_id):
        """Get task status."""
        try:
            task_mgr = get_task_manager()
            status = task_mgr.get_task_status(task_id)
            
            if not status:
                return jsonify({'success': False, 'error': 'Task not found'}), 404
            
            return jsonify({
                'success': True,
                'task': status
            })
        except Exception as e:
            logger.error(f"Error getting task status: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/tasks')
    def api_all_tasks():
        """Get all tasks. Optionally return lightweight version without full output."""
        try:
            task_mgr = get_task_manager()
            tasks = task_mgr.get_all_tasks()
            
            # Check if lightweight version is requested (for faster loading)
            lightweight = request.args.get('lightweight', 'false').lower() == 'true'
            
            if lightweight:
                # Return tasks without full output to reduce payload size
                lightweight_tasks = {}
                for task_id, task in tasks.items():
                    lightweight_task = {
                        'status': task.get('status'),
                        'started_at': task.get('started_at'),
                        'finished_at': task.get('finished_at'),
                        'script': task.get('script'),
                        'progress': task.get('progress'),
                        'message': task.get('message'),
                        'current_action': task.get('current_action'),
                        'pid': task.get('pid'),
                        'return_code': task.get('return_code'),
                        'error': task.get('error'),
                        'steps': task.get('steps'),
                        'current_step': task.get('current_step'),
                        'total_steps': task.get('total_steps')
                    }
                    # Include only last 500 chars of output if exists
                    if 'output' in task and task['output']:
                        output = task['output']
                        if len(output) > 500:
                            lightweight_task['output'] = '...' + output[-500:]
                        else:
                            lightweight_task['output'] = output
                    lightweight_tasks[task_id] = lightweight_task
                
                return jsonify({
                    'success': True,
                    'tasks': lightweight_tasks,
                    'lightweight': True
                })
            else:
                return jsonify({
                    'success': True,
                    'tasks': tasks
                })
        except Exception as e:
            logger.error(f"Error getting tasks: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/tasks/<task_id>/cancel', methods=['POST'])
    @requires_auth
    def api_cancel_task(task_id):
        """Cancel a running task."""
        try:
            task_mgr = get_task_manager()
            success = task_mgr.cancel_task(task_id)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': f'Task {task_id} cancelled successfully'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': f'Failed to cancel task {task_id}'
                }), 400
        except Exception as e:
            logger.error(f"Error cancelling task: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/tasks/clear-completed', methods=['POST'])
    @requires_auth
    def api_clear_completed_tasks():
        """Clear all completed, failed, and cancelled tasks."""
        try:
            task_mgr = get_task_manager()
            count = task_mgr.clear_completed_tasks()
            
            return jsonify({
                'success': True,
                'message': f'Cleared {count} task(s)',
                'count': count
            })
        except Exception as e:
            logger.error(f"Error clearing tasks: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/tasks/<task_id>/last-log')
    def api_task_last_log(task_id):
        """Get last log line for a task. Optimized for fast response."""
        try:
            task_mgr = get_task_manager()
            log_file = task_mgr.get_task_log_file(task_id)
            
            if not log_file or not os.path.exists(log_file):
                return jsonify({
                    'success': True,
                    'log_line': None,
                    'timestamp': None
                })
            
            # Read last line from log file (optimized for large files)
            try:
                # Read last 8KB of file to find last line (more efficient than reading entire file)
                with open(log_file, 'rb') as f:
                    # Seek to end
                    f.seek(0, 2)
                    file_size = f.tell()
                    
                    if file_size == 0:
                        return jsonify({
                            'success': True,
                            'log_line': None,
                            'timestamp': None
                        })
                    
                    # Read last 8KB (or entire file if smaller)
                    read_size = min(8192, file_size)
                    f.seek(max(0, file_size - read_size))
                    chunk = f.read(read_size).decode('utf-8', errors='replace')
                    
                    # Find last line
                    lines = chunk.splitlines()
                    if lines:
                        last_line = lines[-1].strip()
                        # Try to extract timestamp from log line
                        timestamp = None
                        if last_line:
                            # Log format: "2025-12-21 13:00:55,727 - INFO - ..."
                            import re
                            match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', last_line)
                            if match:
                                timestamp = match.group(1)
                        
                        return jsonify({
                            'success': True,
                            'log_line': last_line,
                            'timestamp': timestamp
                        })
                    else:
                        return jsonify({
                            'success': True,
                            'log_line': None,
                            'timestamp': None
                        })
            except Exception as e:
                logger.error(f"Error reading log file {log_file}: {str(e)}")
                return jsonify({
                    'success': True,
                    'log_line': None,
                    'timestamp': None
                })
                
        except Exception as e:
            logger.error(f"Error getting task log: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/settings', methods=['GET'])
    def api_get_settings():
        """Get current settings."""
        try:
            settings_dict = {
                'SCRAPER_BATCH_SIZE': settings.SCRAPER_BATCH_SIZE,
                'SCRAPER_REQUEST_DELAY': settings.SCRAPER_REQUEST_DELAY,
                'VERSION_AGE_LIMIT_DAYS': settings.VERSION_AGE_LIMIT_DAYS,
                'MAX_CONCURRENT_DOWNLOADS': settings.MAX_CONCURRENT_DOWNLOADS,
                'MAX_VERSION_SCRAPER_WORKERS': settings.MAX_VERSION_SCRAPER_WORKERS,
                'MAX_RETRY_ATTEMPTS': settings.MAX_RETRY_ATTEMPTS,
            }
            
            return jsonify({
                'success': True,
                'settings': settings_dict
            })
        except Exception as e:
            logger.error(f"Error getting settings: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/settings', methods=['POST'])
    def api_update_settings():
        """Update settings in .env file."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': 'No data provided'}), 400
            
            # Allowed settings to update
            allowed_settings = [
                'SCRAPER_BATCH_SIZE',
                'SCRAPER_REQUEST_DELAY',
                'VERSION_AGE_LIMIT_DAYS',
                'MAX_CONCURRENT_DOWNLOADS',
                'MAX_VERSION_SCRAPER_WORKERS',
                'MAX_RETRY_ATTEMPTS'
            ]
            
            updated = []
            errors = []
            
            for key, value in data.items():
                if key not in allowed_settings:
                    errors.append(f"Setting '{key}' is not allowed to be updated")
                    continue
                
                # Validate value
                try:
                    if key in ['SCRAPER_BATCH_SIZE', 'MAX_CONCURRENT_DOWNLOADS', 
                              'MAX_VERSION_SCRAPER_WORKERS', 'MAX_RETRY_ATTEMPTS', 
                              'VERSION_AGE_LIMIT_DAYS']:
                        int(value)  # Validate it's a number
                    elif key == 'SCRAPER_REQUEST_DELAY':
                        float(value)  # Validate it's a float
                except (ValueError, TypeError):
                    errors.append(f"Invalid value for '{key}': must be a number")
                    continue
                
                # Update setting
                if update_env_setting(key, str(value)):
                    updated.append(key)
                else:
                    errors.append(f"Failed to update '{key}'")
            
            if errors:
                return jsonify({
                    'success': False,
                    'errors': errors,
                    'updated': updated
                }), 400
            
            return jsonify({
                'success': True,
                'message': f'Updated {len(updated)} setting(s). Restart the application to apply changes.',
                'updated': updated,
                'note': 'You need to restart the Flask application for changes to take effect.'
            })
        except Exception as e:
            logger.error(f"Error updating settings: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/storage-paths', methods=['GET'])
    def api_get_storage_paths():
        """Get current storage paths."""
        try:
            env_settings = read_env_settings()
            paths = {
                'METADATA_DIR': env_settings.get('METADATA_DIR', settings.METADATA_DIR),
                'DATABASE_PATH': env_settings.get('DATABASE_PATH', settings.DATABASE_PATH),
                'DESCRIPTIONS_DIR': env_settings.get('DESCRIPTIONS_DIR', settings.DESCRIPTIONS_DIR),
                'LOGS_DIR': env_settings.get('LOGS_DIR', settings.LOGS_DIR),
                'BINARIES_BASE_DIR': env_settings.get('BINARIES_BASE_DIR', settings.BINARIES_BASE_DIR),
                'BINARIES_DIR_JIRA': env_settings.get('BINARIES_DIR_JIRA', settings.PRODUCT_STORAGE_MAP.get('jira', '')),
                'BINARIES_DIR_CONFLUENCE': env_settings.get('BINARIES_DIR_CONFLUENCE', settings.PRODUCT_STORAGE_MAP.get('confluence', '')),
                'BINARIES_DIR_BITBUCKET': env_settings.get('BINARIES_DIR_BITBUCKET', settings.PRODUCT_STORAGE_MAP.get('bitbucket', '')),
                'BINARIES_DIR_BAMBOO': env_settings.get('BINARIES_DIR_BAMBOO', settings.PRODUCT_STORAGE_MAP.get('bamboo', '')),
                'BINARIES_DIR_CROWD': env_settings.get('BINARIES_DIR_CROWD', settings.PRODUCT_STORAGE_MAP.get('crowd', '')),
            }
            
            return jsonify({
                'success': True,
                'paths': paths
            })
        except Exception as e:
            logger.error(f"Error getting storage paths: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/storage-paths', methods=['POST'])
    def api_update_storage_paths():
        """Update storage paths in .env file."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': 'No data provided'}), 400
            
            # Allowed path settings
            allowed_paths = [
                'METADATA_DIR',
                'DATABASE_PATH',
                'DESCRIPTIONS_DIR',
                'LOGS_DIR',
                'BINARIES_BASE_DIR',
                'BINARIES_DIR_JIRA',
                'BINARIES_DIR_CONFLUENCE',
                'BINARIES_DIR_BITBUCKET',
                'BINARIES_DIR_BAMBOO',
                'BINARIES_DIR_CROWD',
            ]
            
            updated = []
            errors = []
            
            for key, value in data.items():
                if key not in allowed_paths:
                    errors.append(f"Path '{key}' is not allowed to be updated")
                    continue
                
                # Validate path (basic check - should be a string)
                if not isinstance(value, str):
                    errors.append(f"Invalid path for '{key}': must be a string")
                    continue
                
                # Normalize path (remove trailing slashes, normalize separators)
                # Empty paths are allowed (will use defaults)
                normalized_path = os.path.normpath(value.strip()) if value.strip() else ''
                
                # Update setting
                if update_env_setting(key, normalized_path):
                    updated.append(key)
                else:
                    errors.append(f"Failed to update '{key}'")
            
            if errors:
                return jsonify({
                    'success': False,
                    'errors': errors,
                    'updated': updated
                }), 400
            
            return jsonify({
                'success': True,
                'message': f'Updated {len(updated)} path(s). Restart the application to apply changes.',
                'updated': updated,
                'note': 'You need to restart the Flask application for changes to take effect.'
            })
        except Exception as e:
            logger.error(f"Error updating storage paths: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/credentials', methods=['GET'])
    def api_get_credentials():
        """Get credentials (masked). Supports multiple accounts."""
        try:
            from utils.credentials import get_credentials, get_all_credentials, get_credentials_rotator
            # Get all accounts
            all_accounts = get_all_credentials()
            # Get single credentials for backward compatibility
            single_creds = get_credentials()
            rotator = get_credentials_rotator()
            
            return jsonify({
                'success': True,
                'accounts': [
                    {
                        'username': acc.get('username', ''),
                        'api_token': '***' if acc.get('api_token') else ''
                    }
                    for acc in all_accounts
                ],
                'single': {
                    'username': single_creds.get('username', ''),
                    'api_token': '***' if single_creds.get('api_token') else ''
                },
                'count': len(all_accounts),
                'rotation_enabled': rotator.count() > 1
            })
        except Exception as e:
            logger.error(f"Error getting credentials: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/credentials', methods=['POST'])
    def api_update_credentials():
        """Update credentials. Supports both single and multiple accounts."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': 'No data provided'}), 400
            
            # Check if it's multiple accounts update
            if 'accounts' in data and isinstance(data['accounts'], list):
                from utils.credentials import save_multiple_credentials
                accounts = []
                for acc in data['accounts']:
                    username = acc.get('username', '').strip()
                    api_token = acc.get('api_token', '').strip()
                    if username and api_token:
                        accounts.append({
                            'username': username,
                            'api_token': api_token
                        })
                
                if save_multiple_credentials(accounts):
                    # Reload rotator
                    from utils.credentials import get_credentials_rotator
                    get_credentials_rotator().reload()
                    return jsonify({
                        'success': True,
                        'message': f'Saved {len(accounts)} account(s) successfully'
                    })
                else:
                    return jsonify({'success': False, 'error': 'Failed to save credentials'}), 500
            else:
                # Single account update (backward compatibility)
                username = data.get('username', '').strip()
                api_token = data.get('api_token', '').strip()
                
                from utils.credentials import save_credentials
                if save_credentials(username, api_token):
                    # Reload rotator
                    from utils.credentials import get_credentials_rotator
                    get_credentials_rotator().reload()
                    return jsonify({
                        'success': True,
                        'message': 'Credentials saved successfully'
                    })
                else:
                    return jsonify({'success': False, 'error': 'Failed to save credentials'}), 500
        except Exception as e:
            logger.error(f"Error updating credentials: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/logs')
    def api_logs():
        """Get log files list."""
        try:
            log_files = []
            logs_dir = settings.LOGS_DIR
            
            if os.path.exists(logs_dir):
                for file in os.listdir(logs_dir):
                    if file.endswith('.log') or ('.log.' in file and file.split('.log.')[-1].isdigit()):
                        file_path = os.path.join(logs_dir, file)
                        try:
                            stat = os.stat(file_path)
                            log_files.append({
                                'name': file,
                                'size': stat.st_size,
                                'modified': stat.st_mtime
                            })
                        except Exception:
                            pass
            
            # Sort by modified time (newest first)
            log_files.sort(key=lambda x: x['modified'], reverse=True)
            
            return jsonify({
                'success': True,
                'logs': log_files
            })
        except Exception as e:
            logger.error(f"Error getting logs: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/logs/<log_name>')
    def api_log_content(log_name):
        """Get log file content."""
        try:
            # Security: only allow .log files
            if not (log_name.endswith('.log') or ('.log.' in log_name and log_name.split('.log.')[-1].isdigit())):
                return jsonify({'success': False, 'error': 'Invalid log file'}), 400
            
            # Security: prevent directory traversal
            log_name = os.path.basename(log_name)
            
            log_path = os.path.join(settings.LOGS_DIR, log_name)
            if not os.path.exists(log_path):
                return jsonify({'success': False, 'error': 'Log file not found'}), 404
            
            # Read last N lines (default 500)
            lines = request.args.get('lines', 500, type=int)
            
            try:
                with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                    all_lines = f.readlines()
                    # Get last N lines
                    content = ''.join(all_lines[-lines:]) if len(all_lines) > lines else ''.join(all_lines)
                
                return jsonify({
                    'success': True,
                    'content': content,
                    'total_lines': len(all_lines),
                    'showing': min(lines, len(all_lines))
                })
            except Exception as e:
                return jsonify({'success': False, 'error': f'Error reading log: {str(e)}'}), 500
                
        except Exception as e:
            logger.error(f"Error getting log content: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.errorhandler(404)
    def not_found(e):
        """Handle 404 errors."""
        logger.error(f"404 error: {str(e)}")
        return render_template('error.html', error='Page not found'), 404

    @app.errorhandler(500)
    def server_error(e):
        """Handle 500 errors."""
        logger.error(f"500 error: {str(e)}", exc_info=True)
        return render_template('error.html', error='Internal server error'), 500
