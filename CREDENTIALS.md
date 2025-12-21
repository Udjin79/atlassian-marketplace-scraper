# Credentials Management

This document explains how to configure credentials for the Atlassian Marketplace Scraper.

## Overview

The scraper supports two credential modes:

1. **Simple Mode**: Single account credentials in `.env` file
2. **Advanced Mode**: Multiple encrypted accounts in `.credentials.json` file with automatic rotation

## Simple Mode (Single Account)

Best for: Personal use, single account, quick setup

### Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set your credentials:
   ```ini
   MARKETPLACE_USERNAME=your-email@example.com
   MARKETPLACE_API_TOKEN=your-api-token-here
   ```

3. Get your API token from: https://id.atlassian.com/manage-profile/security/api-tokens

### Limitations

- Single account only
- Credentials stored in plain text (within `.env`)
- No automatic rate limit avoidance
- `.env` file must not be committed to git

## Advanced Mode (Multiple Accounts - Recommended)

Best for: Production use, multiple accounts, better rate limit handling

### Benefits

- **Multiple Accounts**: Support for 2+ Atlassian accounts
- **Automatic Rotation**: Round-robin or random selection between accounts
- **Encryption**: Credentials encrypted using Fernet symmetric encryption
- **Rate Limit Avoidance**: Distribute requests across multiple accounts
- **Git-Safe**: `.credentials.json` is in `.gitignore`

### Setup

#### Option 1: Using the Web Interface

1. Start the web application:
   ```bash
   python app.py
   ```

2. Navigate to the Management page

3. Add accounts through the web interface

#### Option 2: Manual Configuration

1. Create `.credentials.json` file in the project root (if it doesn't exist)

2. Add your credentials in the following format:
   ```json
   {
     "encrypted": false,
     "accounts": [
       {
         "username": "account1@example.com",
         "api_token": "token1"
       },
       {
         "username": "account2@example.com",
         "api_token": "token2"
       }
     ]
   }
   ```

3. The system will automatically encrypt the credentials on first save

#### Option 3: Using Python

```python
from utils.credentials import save_multiple_credentials

accounts = [
    {"username": "account1@example.com", "api_token": "token1"},
    {"username": "account2@example.com", "api_token": "token2"}
]

save_multiple_credentials(accounts)
```

### Credential Rotation

The system provides a `CredentialsRotator` class that automatically rotates between accounts:

```python
from utils.credentials import get_credentials_rotator

rotator = get_credentials_rotator()

# Get next account in round-robin
creds = rotator.get_next()

# Get random account
creds = rotator.get_random()

# Get all accounts
all_creds = rotator.get_all()

# Get account count
count = rotator.count()
```

## Fallback Behavior

The system uses the following priority for loading credentials:

1. **Primary**: `.credentials.json` file
   - Supports multiple accounts
   - Encrypted storage
   - Automatic rotation

2. **Fallback**: `.env` file
   - Single account only
   - Used if `.credentials.json` is missing or empty
   - Reads `MARKETPLACE_USERNAME` and `MARKETPLACE_API_TOKEN`

This allows you to start with simple mode and upgrade to advanced mode without code changes.

## Encryption

### Encryption Key

The system uses Fernet encryption with a machine-specific key stored in `.encryption_key`.

- **Key Location**: `.encryption_key` file in project root
- **Key Generation**: Automatic on first use
- **Security**: Keep this file secure; losing it means losing access to encrypted credentials

### Requirements

Install the cryptography library for full encryption support:

```bash
pip install cryptography
```

If not installed, the system falls back to basic XOR obfuscation (less secure).

## Security Best Practices

1. **Never commit credentials to git**:
   - `.env` is in `.gitignore`
   - `.credentials.json` is in `.gitignore`
   - `.encryption_key` is in `.gitignore`

2. **Use strong API tokens**:
   - Generate from: https://id.atlassian.com/manage-profile/security/api-tokens
   - Rotate periodically
   - Revoke unused tokens

3. **Protect credential files**:
   - Set appropriate file permissions (read/write for owner only)
   - Don't share `.encryption_key` between machines
   - Back up `.credentials.json` and `.encryption_key` together

4. **Admin credentials**:
   - Set strong `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `.env`
   - Required for accessing the Management interface
   - Use HTTPS in production

## Troubleshooting

### "Credentials empty" Error

**Problem**: Application can't find credentials

**Solutions**:
1. Check `.credentials.json` exists and has accounts
2. Verify `.env` has `MARKETPLACE_USERNAME` and `MARKETPLACE_API_TOKEN`
3. Check file permissions (must be readable)
4. Review logs in `logs/credentials.log`

### "Decryption Failed" Error

**Problem**: Can't decrypt credentials from `.credentials.json`

**Solutions**:
1. Verify `.encryption_key` file exists
2. Don't move `.encryption_key` between machines
3. If key is lost, you'll need to recreate `.credentials.json` from scratch
4. Check `cryptography` library is installed: `pip install cryptography`

### "Invalid API Token" Error

**Problem**: Atlassian API rejects your token

**Solutions**:
1. Verify token is correct (no extra spaces)
2. Check token hasn't expired or been revoked
3. Generate new token from: https://id.atlassian.com/manage-profile/security/api-tokens
4. Ensure username matches the account that created the token

### Multiple Accounts Not Rotating

**Problem**: System only uses one account

**Solutions**:
1. Verify `.credentials.json` has multiple accounts in `accounts` array
2. Check logs to see which accounts are loaded
3. Reload credentials: `rotator.reload()`
4. Verify all accounts have valid credentials

## File Structure

```
project/
├── .env                    # Environment variables (not in git)
├── .credentials.json       # Encrypted credentials (not in git)
├── .encryption_key         # Encryption key (not in git)
├── .env.example           # Example environment file (in git)
└── CREDENTIALS.md         # This documentation (in git)
```

## Migration Guide

### From .env to .credentials.json

1. Note your current credentials from `.env`
2. Create `.credentials.json` with your credentials
3. (Optional) Remove or comment out credentials in `.env`
4. The system will automatically prefer `.credentials.json`

### Adding More Accounts

1. Get additional Atlassian API tokens
2. Add accounts via web interface or edit `.credentials.json`
3. System automatically uses all accounts for rotation

## API Reference

### get_credentials()

Returns first available credential set (for backward compatibility).

```python
from utils.credentials import get_credentials

creds = get_credentials()
# Returns: {'username': 'email@example.com', 'api_token': 'token'}
```

### get_all_credentials()

Returns all available credential sets.

```python
from utils.credentials import get_all_credentials

all_creds = get_all_credentials()
# Returns: [{'username': '...', 'api_token': '...'}, ...]
```

### save_credentials(username, api_token)

Save single credential set (maintains backward compatibility).

```python
from utils.credentials import save_credentials

success = save_credentials('email@example.com', 'token')
```

### save_multiple_credentials(accounts)

Save multiple credential sets at once.

```python
from utils.credentials import save_multiple_credentials

accounts = [
    {'username': 'email1@example.com', 'api_token': 'token1'},
    {'username': 'email2@example.com', 'api_token': 'token2'}
]
success = save_multiple_credentials(accounts)
```

### CredentialsRotator Class

Thread-safe credential rotation manager.

```python
from utils.credentials import get_credentials_rotator

rotator = get_credentials_rotator()
next_cred = rotator.get_next()      # Round-robin
random_cred = rotator.get_random()  # Random selection
all_creds = rotator.get_all()       # All credentials
count = rotator.count()             # Number of accounts
rotator.reload()                    # Reload from file
```
