"""Main Flask application entry point."""

import os
from flask import Flask
from config import settings
from web.routes import register_routes
from utils.logger import setup_logging


def create_app():
    """Create and configure the Flask application."""
    # Get the base directory
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Create Flask app with correct template and static folders
    app = Flask(
        __name__,
        template_folder=os.path.join(base_dir, 'web', 'templates'),
        static_folder=os.path.join(base_dir, 'web', 'static')
    )

    # Configuration
    app.config['SECRET_KEY'] = settings.SECRET_KEY
    app.config['DEBUG'] = settings.FLASK_DEBUG

    # Setup logging
    setup_logging()

    # Register routes
    register_routes(app)

    return app


if __name__ == '__main__':
    app = create_app()

    print("=" * 60)
    print("🚀 Atlassian Marketplace Scraper - Web Interface")
    print("=" * 60)
    print(f"📍 Server: http://localhost:{settings.FLASK_PORT}")
    print(f"🔧 Debug mode: {settings.FLASK_DEBUG}")
    print("=" * 60)
    print("\n💡 Tips:")
    print("   - Run scraper first to populate data")
    print("   - Use /api/stats to check progress")
    print("   - Browse /apps to view collected apps\n")

    app.run(
        host='0.0.0.0',
        port=settings.FLASK_PORT,
        debug=settings.FLASK_DEBUG
    )
