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
    import socket
    import sys
    
    # Check if port is available
    def is_port_available(port):
        """Check if a port is available."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('127.0.0.1', port))
            sock.close()
            return True
        except OSError:
            return False
    
    try:
        app = create_app()
        
        # Check port availability
        if not is_port_available(settings.FLASK_PORT):
            print("=" * 60)
            print("❌ ERROR: Port is already in use!")
            print("=" * 60)
            print(f"Port {settings.FLASK_PORT} is already occupied.")
            print("\nSolutions:")
            print(f"1. Change FLASK_PORT in .env file to another port (e.g., 5001)")
            print("2. Close the application using this port")
            print("3. Find and kill the process:")
            print(f"   netstat -ano | findstr :{settings.FLASK_PORT}")
            sys.exit(1)

        print("=" * 60)
        print("🚀 Atlassian Marketplace Scraper - Web Interface")
        print("=" * 60)
        print(f"📍 Server: http://localhost:{settings.FLASK_PORT}")
        print(f"📍 Also available at: http://127.0.0.1:{settings.FLASK_PORT}")
        print(f"🔧 Debug mode: {settings.FLASK_DEBUG}")
        print("=" * 60)
        print("\n💡 Tips:")
        print("   - Run scraper first to populate data")
        print("   - Use /api/stats to check progress")
        print("   - Browse /apps to view collected apps")
        print("\n⚠️  Press CTRL+C to stop the server\n")

        app.run(
            host='0.0.0.0',
            port=settings.FLASK_PORT,
            debug=settings.FLASK_DEBUG,
            use_reloader=False  # Disable reloader to avoid issues
        )
        
    except Exception as e:
        print("=" * 60)
        print("❌ ERROR: Failed to start Flask application")
        print("=" * 60)
        print(f"Error: {str(e)}")
        print("\nTroubleshooting:")
        print("1. Check if virtual environment is activated")
        print("2. Verify all dependencies are installed: pip install -r requirements.txt")
        print("3. Check database exists: I:\\marketplace\\marketplace.db")
        print("4. Review logs in I:\\marketplace\\logs\\")
        import traceback
        traceback.print_exc()
        sys.exit(1)
