"""Settings manager for reading and updating .env file."""

import os
from typing import Dict
from utils.logger import get_logger

logger = get_logger('settings_manager')


def _sanitize_for_log(value: str, max_length: int = 200) -> str:
    """Sanitize user input for safe logging to prevent log injection.

    Removes newlines and control characters that could be used to inject
    fake log entries or manipulate log analysis tools.

    Args:
        value: The user-provided value to sanitize
        max_length: Maximum length of the output (default 200)

    Returns:
        A sanitized string safe for logging
    """
    if value is None:
        return '<None>'
    if not isinstance(value, str):
        value = str(value)
    # Replace newlines that could inject fake log entries
    sanitized = value.replace('\n', '\\n').replace('\r', '\\r')
    # Replace other control characters
    sanitized = ''.join(char if ord(char) >= 32 or char == '\t' else f'\\x{ord(char):02x}' for char in sanitized)
    # Truncate to max length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + '...[truncated]'
    return sanitized


def get_env_file_path() -> str:
    """Get path to .env file.

    In Docker environments, .env file is typically not copied into the container
    (excluded via .dockerignore) and environment variables are passed via env_file
    directive in docker-compose.yml. For settings modification to work in Docker,
    mount the .env file as a volume:

        volumes:
          - ./.env:/app/.env
    """
    # Check for ENV_FILE_PATH override first (useful for Docker)
    env_file_path = os.environ.get('ENV_FILE_PATH')
    if env_file_path and os.path.exists(env_file_path):
        return env_file_path

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, '.env')


def read_env_settings() -> Dict[str, str]:
    """
    Read settings from .env file.

    Returns:
        Dictionary of setting names and values
    """
    env_path = get_env_file_path()
    settings_dict = {}

    if not os.path.exists(env_path):
        # Only warn if decouple can't find it either (avoid false warnings in Docker)
        try:
            from decouple import config
            # Test if decouple can load config from any location
            config('LOG_LEVEL', default='INFO')
            # If we get here, decouple found a config file somewhere
            logger.debug(f".env file not at {env_path}, but decouple found config elsewhere")
        except Exception:
            logger.warning(f".env file not found at {env_path}")
        return settings_dict
    
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                
                # Parse KEY=VALUE
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    settings_dict[key] = value
    except Exception as e:
        logger.error(f"Error reading .env file: {str(e)}")
    
    return settings_dict


def update_env_setting(key: str, value: str) -> bool:
    """
    Update a setting in .env file.

    Args:
        key: Setting key
        value: Setting value (can be empty string)

    Returns:
        True if successful, False otherwise
    """
    env_path = get_env_file_path()

    if not os.path.exists(env_path):
        # Check if running in Docker without .env mounted
        is_docker = os.path.exists('/.dockerenv') or os.environ.get('DOCKER_CONTAINER')
        if is_docker:
            logger.error(
                f".env file not found at {env_path}. "
                "In Docker, mount .env as a volume: './.env:/app/.env' in docker-compose.yml"
            )
        else:
            logger.error(f".env file not found at {env_path}")
        return False
    
    try:
        # Read current content
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Update or add setting
        updated = False
        new_lines = []
        
        for line in lines:
            # Check if line starts with key= (with optional whitespace)
            stripped = line.strip()
            if stripped.startswith(f'{key}='):
                # Update the line
                new_lines.append(f'{key}={value}\n')
                updated = True
            else:
                new_lines.append(line)
        
        # If not found, add at the end
        if not updated:
            new_lines.append(f'{key}={value}\n')
        
        # Write back
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        logger.info(f"Updated {_sanitize_for_log(key)} in .env file")
        return True
        
    except Exception as e:
        logger.error(f"Error updating .env file: {str(e)}")
        return False


def update_env_settings(settings_dict: Dict[str, str]) -> Dict[str, bool]:
    """
    Update multiple settings in .env file at once.
    
    Args:
        settings_dict: Dictionary of setting keys and values
        
    Returns:
        Dictionary mapping keys to success status (True/False)
    """
    results = {}
    for key, value in settings_dict.items():
        results[key] = update_env_setting(key, value)
    return results

