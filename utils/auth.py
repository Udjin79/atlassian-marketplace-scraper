"""Authentication utilities for protecting management endpoints."""

from functools import wraps
from flask import request, jsonify, make_response
from config import settings


def check_auth(username, password):
    """
    Check if username/password combination is valid.

    Args:
        username: Username to check
        password: Password to check

    Returns:
        True if credentials are valid, False otherwise
    """
    return username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD


def authenticate():
    """Send a 401 response that enables basic auth."""
    message = {'success': False, 'error': 'Authentication required', 'message': 'Please provide valid credentials'}
    response = make_response(jsonify(message), 401)
    response.headers['WWW-Authenticate'] = 'Basic realm="Management Area"'
    return response


def requires_auth(f):
    """
    Decorator to require HTTP Basic Authentication for a route.

    Usage:
        @app.route('/protected')
        @requires_auth
        def protected_route():
            return 'This is protected'
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated
