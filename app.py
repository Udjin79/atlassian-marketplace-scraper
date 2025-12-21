"""Main Flask application entry point."""

import os
import sys
import subprocess
from flask import Flask
from flask_wtf.csrf import CSRFProtect
from config import settings
from web.routes import register_routes
from utils.logger import setup_logging, get_logger

logger = get_logger('app')


def check_requirements():
    """Check if all required packages from requirements.txt are installed."""
    try:
        requirements_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'requirements.txt')
        if not os.path.exists(requirements_path):
            logger.warning("requirements.txt not found, skipping package check")
            return True
        
        with open(requirements_path, 'r', encoding='utf-8') as f:
            requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        
        # Map package names to their import names
        package_import_map = {
            'python-decouple': 'decouple',
            'beautifulsoup4': 'bs4',
            'flask-wtf': 'flask_wtf',
            'lxml': 'lxml',
            'playwright': 'playwright',
            'flask': 'flask',
            'requests': 'requests',
            'pandas': 'pandas',
            'tqdm': 'tqdm'
        }
        
        missing_packages = []
        for req in requirements:
            # Parse package name (handle version specifiers)
            package_name = req.split('==')[0].split('>=')[0].split('<=')[0].split('>')[0].split('<')[0].strip()
            # Get import name (use mapping or default to package name with dashes replaced)
            import_name = package_import_map.get(package_name, package_name.replace('-', '_'))
            
            try:
                __import__(import_name)
            except ImportError:
                missing_packages.append(package_name)
        
        if missing_packages:
            logger.warning(f"Missing required packages: {', '.join(missing_packages)}")
            print("=" * 60)
            print("⚠️  WARNING: Missing required packages!")
            print("=" * 60)
            print(f"Attempting to install missing packages automatically...")
            print()
            
            # Try to install missing packages automatically
            import subprocess
            import sys
            
            try:
                # Install missing packages
                result = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install'] + missing_packages,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout
                )
                
                if result.returncode == 0:
                    print("✅ Successfully installed missing packages!")
                    print("=" * 60)
                    # Verify installation
                    still_missing = []
                    for pkg in missing_packages:
                        import_name = package_import_map.get(pkg, pkg.replace('-', '_'))
                        try:
                            __import__(import_name)
                        except ImportError:
                            still_missing.append(pkg)
                    
                    if still_missing:
                        print("⚠️  Some packages could not be installed:")
                        print(f"  {', '.join(still_missing)}")
                        print(f"\nPlease install manually:")
                        print(f"  pip install {' '.join(still_missing)}")
                        print("=" * 60)
                        return False
                    else:
                        print("✅ All packages are now installed!")
                        print("=" * 60)
                        return True
                else:
                    print("❌ Failed to install packages automatically:")
                    print(result.stderr)
                    print(f"\nPlease install manually:")
                    print(f"  pip install {' '.join(missing_packages)}")
                    print(f"\nOr install all requirements:")
                    print(f"  pip install -r requirements.txt")
                    print("=" * 60)
                    return False
            except subprocess.TimeoutExpired:
                print("❌ Installation timed out. Please install manually:")
                print(f"  pip install {' '.join(missing_packages)}")
                print("=" * 60)
                return False
            except Exception as e:
                print(f"❌ Error during automatic installation: {str(e)}")
                print(f"\nPlease install manually:")
                print(f"  pip install {' '.join(missing_packages)}")
                print(f"\nOr install all requirements:")
                print(f"  pip install -r requirements.txt")
                print("=" * 60)
                return False
        
        logger.info("All required packages are installed")
        return True
    except Exception as e:
        logger.error(f"Error checking requirements: {str(e)}")
        return True  # Don't block startup on check failure


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

    # Security: Secure cookie settings
    app.config['SESSION_COOKIE_SECURE'] = not settings.FLASK_DEBUG  # HTTPS only in production
    app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
    app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour session timeout

    # CSRF Protection
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['WTF_CSRF_TIME_LIMIT'] = None  # Tokens don't expire (rely on session timeout)
    app.config['WTF_CSRF_SSL_STRICT'] = not settings.FLASK_DEBUG  # Strict HTTPS in production
    csrf = CSRFProtect(app)

    # Security headers
    @app.after_request
    def set_security_headers(response):
        """Add security headers to all responses."""
        # Prevent clickjacking
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # XSS protection (legacy but still useful)
        response.headers['X-XSS-Protection'] = '1; mode=block'
        # Referrer policy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        # HTTPS enforcement (only in production)
        if not settings.FLASK_DEBUG:
            # Enforce HTTPS for 1 year
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        return response

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
        # Check requirements first
        if not check_requirements():
            sys.exit(1)
        
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
