"""Settings manager for reading and updating .env file."""

import os
import re
from typing import Dict, Optional
from config import settings
from utils.logger import get_logger

logger = get_logger('settings_manager')


def get_env_file_path() -> str:
    """Get path to .env file."""
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
        value: Setting value
        
    Returns:
        True if successful, False otherwise
    """
    env_path = get_env_file_path()
    
    if not os.path.exists(env_path):
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
            if line.strip().startswith(f'{key}='):
                new_lines.append(f'{key}={value}\n')
                updated = True
            else:
                new_lines.append(line)
        
        # If not found, add at the end
        if not updated:
            new_lines.append(f'\n{key}={value}\n')
        
        # Write back
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        logger.info(f"Updated {key} in .env file")
        return True
        
    except Exception as e:
        logger.error(f"Error updating .env file: {str(e)}")
        return False

