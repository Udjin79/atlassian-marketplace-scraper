"""Flask routes for the web interface."""

import os
from flask import render_template, jsonify, request, send_file, redirect, url_for
from config import settings
from config.products import PRODUCTS, PRODUCT_LIST
from scraper.metadata_store import MetadataStore
from scraper.download_manager import DownloadManager
from utils.logger import get_logger

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
            # Find the file
            binary_dir = os.path.join(settings.BINARIES_DIR, product, addon_key, version_id)

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

    @app.errorhandler(404)
    def not_found(e):
        """Handle 404 errors."""
        return render_template('error.html', error='Page not found'), 404

    @app.errorhandler(500)
    def server_error(e):
        """Handle 500 errors."""
        return render_template('error.html', error='Internal server error'), 500
