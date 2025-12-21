"""Credentials manager for storing sensitive data separately from .env file."""

import os
import json
from typing import Optional, Dict
from utils.logger import get_logger

logger = get_logger('credentials')

# Credentials file (not in git)
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.credentials.json')


def get_credentials() -> Dict[str, str]:
    """
    Get credentials from .credentials.json file.
    
    Returns:
        Dictionary with credentials (username, api_token)
    """
    if not os.path.exists(CREDENTIALS_FILE):
        return {
            'username': '',
            'api_token': ''
        }
    
    try:
        with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading credentials file: {str(e)}")
        return {
            'username': '',
            'api_token': ''
        }


def save_credentials(username: str, api_token: str) -> bool:
    """
    Save credentials to .credentials.json file.
    
    Args:
        username: Marketplace username
        api_token: Marketplace API token
        
    Returns:
        True if successful, False otherwise
    """
    try:
        credentials = {
            'username': username,
            'api_token': api_token
        }
        
        with open(CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
            json.dump(credentials, f, indent=2)
        
        logger.info("Credentials saved successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving credentials: {str(e)}")
        return False

