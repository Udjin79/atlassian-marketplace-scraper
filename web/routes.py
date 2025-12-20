"""Flask routes for the web interface."""

import os
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

            stats = {
                'total_apps': total_apps,
                'total_versions': total_versions,
                'downloaded_versions': downloaded_versions,
                'pending_downloads': total_versions - downloaded_versions,
                'storage_used_gb': storage_stats.get('total_gb', 0),
                'storage_used_mb': storage_stats.get('total_mb', 0),
                'file_count': storage_stats.get('file_count', 0)
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

            return render_template(
                'app_detail.html',
                app=app,
                versions=versions
            )

        except Exception as e:
            logger.error(f"Error loading app details for {addon_key}: {str(e)}")
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
                'scrape_apps': task_mgr.get_latest_task('scrape_apps'),
                'scrape_versions': task_mgr.get_latest_task('scrape_versions'),
                'download': task_mgr.get_latest_task('download')
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
            
            return render_template(
                'manage.html',
                latest_tasks=latest_tasks,
                current_settings=current_settings,
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

    @app.route('/api/tasks/<task_id>')
    @requires_auth
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
    @requires_auth
    def api_all_tasks():
        """Get all tasks."""
        try:
            task_mgr = get_task_manager()
            tasks = task_mgr.get_all_tasks()
            
            return jsonify({
                'success': True,
                'tasks': tasks
            })
        except Exception as e:
            logger.error(f"Error getting tasks: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/settings', methods=['GET'])
    @requires_auth
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
    @requires_auth
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

    @app.errorhandler(404)
    def not_found(e):
        """Handle 404 errors."""
        return render_template('error.html', error='Page not found'), 404

    @app.errorhandler(500)
    def server_error(e):
        """Handle 500 errors."""
        return render_template('error.html', error='Internal server error'), 500
