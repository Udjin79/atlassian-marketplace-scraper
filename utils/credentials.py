"""Credentials manager for storing sensitive data separately from .env file."""

import os
import json
import base64
import hashlib
import random
import threading
from typing import Optional, Dict, List
from utils.logger import get_logger

logger = get_logger('credentials')

# Credentials file (not in git)
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.credentials.json')
# Encryption key file (machine-specific, not in git)
ENCRYPTION_KEY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.encryption_key')


def _get_or_create_encryption_key() -> bytes:
    """
    Get or create encryption key for credential encryption.

    The key is stored in a file and is machine-specific.
    This provides basic encryption to prevent plain-text credential storage.

    Returns:
        Encryption key as bytes
    """
    try:
        from cryptography.fernet import Fernet

        if os.path.exists(ENCRYPTION_KEY_FILE):
            # Load existing key
            with open(ENCRYPTION_KEY_FILE, 'rb') as f:
                return f.read()
        else:
            # Generate new key
            key = Fernet.generate_key()
            with open(ENCRYPTION_KEY_FILE, 'wb') as f:
                f.write(key)
            logger.info("Generated new encryption key for credentials")
            return key
    except ImportError:
        # Fallback: cryptography library not installed
        # Use a weak XOR-based obfuscation (better than nothing)
        logger.warning("cryptography library not installed - using basic obfuscation. Install with: pip install cryptography")
        # Use a machine-specific key based on hostname
        import socket
        hostname = socket.gethostname()
        key = hashlib.sha256(hostname.encode()).digest()
        return base64.b64encode(key)


def _encrypt_string(plaintext: str) -> str:
    """
    Encrypt a string.

    Args:
        plaintext: String to encrypt

    Returns:
        Base64-encoded encrypted string
    """
    try:
        from cryptography.fernet import Fernet

        key = _get_or_create_encryption_key()
        f = Fernet(key)
        encrypted = f.encrypt(plaintext.encode())
        return base64.b64encode(encrypted).decode()
    except ImportError:
        # Fallback: basic XOR obfuscation
        key = _get_or_create_encryption_key()
        key_bytes = base64.b64decode(key)

        result = bytearray()
        for i, byte in enumerate(plaintext.encode()):
            result.append(byte ^ key_bytes[i % len(key_bytes)])

        return base64.b64encode(result).decode()


def _decrypt_string(encrypted: str) -> str:
    """
    Decrypt a string.

    Args:
        encrypted: Base64-encoded encrypted string

    Returns:
        Decrypted plaintext string
    """
    try:
        from cryptography.fernet import Fernet

        key = _get_or_create_encryption_key()
        f = Fernet(key)
        encrypted_bytes = base64.b64decode(encrypted.encode())
        decrypted = f.decrypt(encrypted_bytes)
        return decrypted.decode()
    except ImportError:
        # Fallback: basic XOR deobfuscation
        key = _get_or_create_encryption_key()
        key_bytes = base64.b64decode(key)

        encrypted_bytes = base64.b64decode(encrypted.encode())
        result = bytearray()
        for i, byte in enumerate(encrypted_bytes):
            result.append(byte ^ key_bytes[i % len(key_bytes)])

        return result.decode()


def get_credentials() -> Dict[str, str]:
    """
    Get credentials from .credentials.json file with fallback to .env.

    Supports both old format (single credentials) and new format (multiple accounts).
    Credentials are automatically decrypted if stored encrypted.

    Fallback priority:
    1. .credentials.json (supports multiple accounts, encrypted)
    2. .env file (simple single account setup)

    Returns:
        Dictionary with credentials (username, api_token)
    """
    credentials = {'username': '', 'api_token': ''}

    # Try loading from .credentials.json first
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

                # Check if encrypted format
                is_encrypted = data.get('encrypted', False)

                # Check if it's the new format with multiple accounts
                if isinstance(data, dict) and 'accounts' in data:
                    # Return first account for backward compatibility
                    accounts = data.get('accounts', [])
                    if accounts:
                        account = accounts[0]
                        if is_encrypted:
                            credentials = {
                                'username': _decrypt_string(account.get('username', '')) if account.get('username') else '',
                                'api_token': _decrypt_string(account.get('api_token', '')) if account.get('api_token') else ''
                            }
                        else:
                            credentials = {
                                'username': account.get('username', ''),
                                'api_token': account.get('api_token', '')
                            }

                # Old format - single credentials
                elif is_encrypted:
                    logger.info("Credentials are encrypted - decrypting")
                    credentials = {
                        'username': _decrypt_string(data.get('username', '')) if data.get('username') else '',
                        'api_token': _decrypt_string(data.get('api_token', '')) if data.get('api_token') else ''
                    }
                else:
                    logger.warning("Credentials are stored in plain text - will be encrypted on next save")
                    credentials = {
                        'username': data.get('username', ''),
                        'api_token': data.get('api_token', '')
                    }
        except Exception as e:
            logger.error(f"Error reading credentials file: {str(e)}")

    # Fallback to .env if credentials are empty
    if not credentials.get('username') or not credentials.get('api_token'):
        logger.info("Credentials empty in .credentials.json, checking .env file")
        try:
            from decouple import config
            env_username = config('MARKETPLACE_USERNAME', default='')
            env_token = config('MARKETPLACE_API_TOKEN', default='')

            if env_username and env_token:
                logger.info("Using credentials from .env file")
                credentials = {
                    'username': env_username,
                    'api_token': env_token
                }
        except Exception as e:
            logger.error(f"Error reading credentials from .env: {str(e)}")

    return credentials


def get_all_credentials() -> List[Dict[str, str]]:
    """
    Get all credentials from .credentials.json file with fallback to .env.
    Credentials are automatically decrypted if stored encrypted.

    Fallback priority:
    1. .credentials.json (supports multiple accounts, encrypted)
    2. .env file (simple single account setup)

    Returns:
        List of dictionaries with credentials (username, api_token)
    """
    accounts = []

    # Try loading from .credentials.json first
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

                # Check if encrypted format
                is_encrypted = data.get('encrypted', False)

                # Check if it's the new format with multiple accounts
                if isinstance(data, dict) and 'accounts' in data:
                    account_list = data.get('accounts', [])
                    if is_encrypted:
                        # Decrypt all accounts
                        for account in account_list:
                            accounts.append({
                                'username': _decrypt_string(account.get('username', '')) if account.get('username') else '',
                                'api_token': _decrypt_string(account.get('api_token', '')) if account.get('api_token') else ''
                            })
                    else:
                        accounts = account_list

                # Old format - single credentials, convert to list
                elif isinstance(data, dict) and 'username' in data and data.get('username'):
                    if is_encrypted:
                        accounts = [{
                            'username': _decrypt_string(data.get('username', '')) if data.get('username') else '',
                            'api_token': _decrypt_string(data.get('api_token', '')) if data.get('api_token') else ''
                        }]
                    else:
                        accounts = [{
                            'username': data.get('username', ''),
                            'api_token': data.get('api_token', '')
                        }]
        except Exception as e:
            logger.error(f"Error reading credentials file: {str(e)}")

    # Fallback to .env if no accounts found
    if not accounts:
        logger.info("No credentials in .credentials.json, checking .env file")
        try:
            from decouple import config
            env_username = config('MARKETPLACE_USERNAME', default='')
            env_token = config('MARKETPLACE_API_TOKEN', default='')

            if env_username and env_token:
                logger.info("Using credentials from .env file")
                accounts = [{
                    'username': env_username,
                    'api_token': env_token
                }]
        except Exception as e:
            logger.error(f"Error reading credentials from .env: {str(e)}")

    return accounts


def save_credentials(username: str, api_token: str) -> bool:
    """
    Save credentials to .credentials.json file.
    Maintains backward compatibility with old format.
    Credentials are encrypted before storage.

    Args:
        username: Marketplace username
        api_token: Marketplace API token

    Returns:
        True if successful, False otherwise
    """
    try:
        # Try to preserve existing accounts if using new format
        existing_accounts = []
        if os.path.exists(CREDENTIALS_FILE):
            try:
                # Get decrypted existing accounts
                existing_accounts = get_all_credentials()
            except:
                pass

        # Check if account already exists
        account_exists = False
        for account in existing_accounts:
            if account.get('username') == username:
                account['api_token'] = api_token
                account_exists = True
                break

        if not account_exists:
            existing_accounts.append({
                'username': username,
                'api_token': api_token
            })

        # Encrypt all accounts
        encrypted_accounts = []
        for account in existing_accounts:
            encrypted_accounts.append({
                'username': _encrypt_string(account['username']) if account.get('username') else '',
                'api_token': _encrypt_string(account['api_token']) if account.get('api_token') else ''
            })

        credentials = {
            'encrypted': True,
            'accounts': encrypted_accounts
        }

        with open(CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
            json.dump(credentials, f, indent=2)

        logger.info(f"Credentials saved successfully (encrypted, {len(existing_accounts)} account(s))")
        return True
    except Exception as e:
        logger.error(f"Error saving credentials: {str(e)}")
        return False


def save_multiple_credentials(accounts: List[Dict[str, str]]) -> bool:
    """
    Save multiple credentials to .credentials.json file.
    Credentials are encrypted before storage.

    Args:
        accounts: List of dictionaries with 'username' and 'api_token'

    Returns:
        True if successful, False otherwise
    """
    try:
        # Encrypt all accounts
        encrypted_accounts = []
        for account in accounts:
            encrypted_accounts.append({
                'username': _encrypt_string(account['username']) if account.get('username') else '',
                'api_token': _encrypt_string(account['api_token']) if account.get('api_token') else ''
            })

        credentials = {
            'encrypted': True,
            'accounts': encrypted_accounts
        }

        with open(CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
            json.dump(credentials, f, indent=2)

        logger.info(f"Saved {len(accounts)} encrypted account(s) successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving credentials: {str(e)}")
        return False


class CredentialsRotator:
    """Manages rotation of multiple API credentials for parallel requests."""

    def __init__(self):
        """Initialize credentials rotator."""
        self._lock = threading.Lock()
        self._accounts: List[Dict[str, str]] = []
        self._current_index = 0
        self._load_accounts()

    def _load_accounts(self):
        """Load accounts from credentials file."""
        with self._lock:
            self._accounts = get_all_credentials()
            if not self._accounts:
                # Fallback to single credentials for backward compatibility
                creds = get_credentials()
                if creds.get('username'):
                    self._accounts = [creds]
            self._current_index = 0

    def get_next(self) -> Optional[Dict[str, str]]:
        """
        Get next credentials in round-robin fashion.

        Returns:
            Dictionary with 'username' and 'api_token', or None if no accounts available
        """
        with self._lock:
            if not self._accounts:
                self._load_accounts()

            if not self._accounts:
                return None

            account = self._accounts[self._current_index]
            self._current_index = (self._current_index + 1) % len(self._accounts)
            return account.copy()

    def get_random(self) -> Optional[Dict[str, str]]:
        """
        Get random credentials.

        Returns:
            Dictionary with 'username' and 'api_token', or None if no accounts available
        """
        with self._lock:
            if not self._accounts:
                self._load_accounts()

            if not self._accounts:
                return None

            return random.choice(self._accounts).copy()

    def get_all(self) -> List[Dict[str, str]]:
        """
        Get all available credentials.

        Returns:
            List of dictionaries with 'username' and 'api_token'
        """
        with self._lock:
            if not self._accounts:
                self._load_accounts()
            return [acc.copy() for acc in self._accounts]

    def count(self) -> int:
        """Get number of available accounts."""
        with self._lock:
            if not self._accounts:
                self._load_accounts()
            return len(self._accounts)

    def reload(self):
        """Reload accounts from file."""
        with self._lock:
            self._load_accounts()


# Global instance
_rotator = None
_rotator_lock = threading.Lock()


def get_credentials_rotator() -> CredentialsRotator:
    """Get global credentials rotator instance."""
    global _rotator
    with _rotator_lock:
        if _rotator is None:
            _rotator = CredentialsRotator()
        return _rotator
