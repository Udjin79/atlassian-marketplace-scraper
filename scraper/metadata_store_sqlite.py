"""Metadata storage and retrieval using SQLite database."""

import json
import os
import sqlite3
from typing import List, Dict, Optional
from config import settings
from models.app import App
from models.version import Version
from utils.logger import get_logger

logger = get_logger('scraper')


class MetadataStoreSQLite:
    """Handles storage and retrieval of app and version metadata using SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize metadata store with SQLite backend.

        Args:
            db_path: Optional path to database file (defaults to settings.DATABASE_PATH)
        """
        self.db_path = db_path or settings.DATABASE_PATH
        self._init_db()

    def _init_db(self):
        """Initialize database schema and indexes if they don't exist."""
        conn = self._get_connection()
        try:
            # Create apps table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS apps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    addon_key TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    vendor TEXT,
                    description TEXT,
                    logo_url TEXT,
                    marketplace_url TEXT,
                    products TEXT,
                    hosting TEXT,
                    categories TEXT,
                    last_updated TEXT,
                    total_versions INTEGER DEFAULT 0,
                    scraped_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create versions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_id INTEGER NOT NULL,
                    addon_key TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    version_name TEXT NOT NULL,
                    build_number TEXT,
                    release_date TEXT,
                    release_notes TEXT,
                    summary TEXT,
                    compatible_products TEXT,
                    compatibility TEXT,
                    hosting_type TEXT,
                    download_url TEXT,
                    file_name TEXT,
                    file_size INTEGER,
                    file_path TEXT,
                    downloaded INTEGER DEFAULT 0,
                    download_date TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (app_id) REFERENCES apps(id) ON DELETE CASCADE,
                    UNIQUE(addon_key, version_id)
                )
            """)
            
            # Migration: Add compatibility column if it doesn't exist
            try:
                conn.execute("ALTER TABLE versions ADD COLUMN compatibility TEXT")
                logger.debug("Added compatibility column to versions table")
            except sqlite3.OperationalError:
                # Column already exists, ignore
                pass

            # Create parent_software_versions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS parent_software_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL,
                    build_number INTEGER NOT NULL,
                    version_number TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(product_id, build_number)
                )
            """)

            # Create indexes
            self._create_indexes(conn)

            conn.commit()
            logger.debug(f"Database initialized at {self.db_path}")

        except sqlite3.Error as e:
            logger.error(f"Error initializing database: {str(e)}")
            raise
        finally:
            conn.close()

    def _create_indexes(self, conn):
        """Create indexes for performance optimization."""
        indexes = [
            # Apps table indexes
            "CREATE INDEX IF NOT EXISTS idx_apps_name ON apps(name COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_apps_vendor ON apps(vendor COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_apps_addon_key ON apps(addon_key)",

            # Versions table indexes
            "CREATE INDEX IF NOT EXISTS idx_versions_app_id ON versions(app_id)",
            "CREATE INDEX IF NOT EXISTS idx_versions_addon_key ON versions(addon_key)",
            "CREATE INDEX IF NOT EXISTS idx_versions_addon_key_release_date ON versions(addon_key, release_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_versions_downloaded ON versions(downloaded)",
            "CREATE INDEX IF NOT EXISTS idx_versions_addon_key_downloaded ON versions(addon_key, downloaded)",

            # Parent software versions table indexes
            "CREATE INDEX IF NOT EXISTS idx_parent_software_product_build ON parent_software_versions(product_id, build_number)"
        ]

        for index_sql in indexes:
            try:
                conn.execute(index_sql)
            except sqlite3.Error as e:
                logger.warning(f"Error creating index: {str(e)}")

    def _get_connection(self):
        """
        Get database connection with WAL mode enabled.

        Returns:
            sqlite3.Connection: Database connection
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Return rows as dict-like objects
        conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for concurrency
        conn.execute("PRAGMA foreign_keys=ON")  # Enable foreign key constraints
        return conn

    def save_app(self, app: App):
        """
        Save or update an app.

        Args:
            app: App instance to save
        """
        conn = self._get_connection()
        try:
            # Handle marketplace_url - can be string or dict
            marketplace_url = app.marketplace_url
            if isinstance(marketplace_url, dict):
                marketplace_url = marketplace_url.get('href', '')

            conn.execute("""
                INSERT OR REPLACE INTO apps (
                    addon_key, name, vendor, description, logo_url,
                    marketplace_url, products, hosting, categories,
                    last_updated, total_versions, scraped_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                app.addon_key,
                app.name,
                app.vendor,
                app.description,
                app.logo_url,
                marketplace_url,
                json.dumps(app.products),
                json.dumps(app.hosting),
                json.dumps(app.categories),
                app.last_updated,
                app.total_versions,
                app.scraped_at
            ))
            conn.commit()
            logger.debug(f"Saved app: {app.addon_key}")

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error saving app {app.addon_key}: {str(e)}")
            raise
        finally:
            conn.close()

    def save_apps_batch(self, apps: List[App]):
        """
        Save multiple apps at once (more efficient with transaction).

        Args:
            apps: List of App instances
        """
        conn = self._get_connection()
        try:
            conn.execute("BEGIN TRANSACTION")

            for app in apps:
                # Handle marketplace_url - can be string or dict
                marketplace_url = app.marketplace_url
                if isinstance(marketplace_url, dict):
                    marketplace_url = marketplace_url.get('href', '')

                conn.execute("""
                    INSERT OR REPLACE INTO apps (
                        addon_key, name, vendor, description, logo_url,
                        marketplace_url, products, hosting, categories,
                        last_updated, total_versions, scraped_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """, (
                    app.addon_key,
                    app.name,
                    app.vendor,
                    app.description,
                    app.logo_url,
                    marketplace_url,
                    json.dumps(app.products),
                    json.dumps(app.hosting),
                    json.dumps(app.categories),
                    app.last_updated,
                    app.total_versions,
                    app.scraped_at
                ))

            conn.commit()
            logger.info(f"Saved batch of {len(apps)} apps")

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Batch save failed: {str(e)}")
            raise
        finally:
            conn.close()

    def get_all_apps(self, filters: Optional[Dict] = None,
                     limit: Optional[int] = None,
                     offset: Optional[int] = 0) -> List[Dict]:
        """
        Get all apps with optional filtering and pagination.

        Args:
            filters: Optional filters (product, search, hosting)
            limit: Maximum apps to return (for pagination)
            offset: Number of apps to skip (for pagination)

        Returns:
            List of app dictionaries
        """
        conn = self._get_connection()

        # Build dynamic WHERE clause
        where_clauses = []
        params = []

        if filters:
            if 'product' in filters and filters['product']:
                # Check if product exists in JSON array
                where_clauses.append("products LIKE ?")
                params.append(f'%"{filters["product"]}"%')

            if 'search' in filters and filters['search']:
                query = filters['search']
                where_clauses.append("""
                    (name LIKE ? OR vendor LIKE ? OR addon_key LIKE ?)
                """)
                params.extend([f'%{query}%', f'%{query}%', f'%{query}%'])

            if 'hosting' in filters and filters['hosting']:
                # Check if hosting type exists in JSON array
                where_clauses.append("hosting LIKE ?")
                params.append(f'%"{filters["hosting"]}"%')

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        # Pagination
        limit_sql = f"LIMIT {limit} OFFSET {offset}" if limit is not None else ""

        sql = f"""
            SELECT * FROM apps
            {where_sql}
            ORDER BY name
            {limit_sql}
        """

        try:
            cursor = conn.execute(sql, params)
            apps = []

            for row in cursor.fetchall():
                app_dict = dict(row)
                # Deserialize JSON fields
                app_dict['products'] = json.loads(app_dict['products']) if app_dict['products'] else []
                app_dict['hosting'] = json.loads(app_dict['hosting']) if app_dict['hosting'] else []
                app_dict['categories'] = json.loads(app_dict['categories']) if app_dict['categories'] else []
                # Remove SQLite-specific fields
                app_dict.pop('id', None)
                app_dict.pop('created_at', None)
                app_dict.pop('updated_at', None)
                apps.append(app_dict)

            return apps

        except sqlite3.Error as e:
            logger.error(f"Error getting apps: {str(e)}")
            return []
        finally:
            conn.close()

    def get_app_by_key(self, addon_key: str) -> Optional[Dict]:
        """
        Get a specific app by its key.

        Args:
            addon_key: The app's unique key

        Returns:
            App dictionary or None
        """
        conn = self._get_connection()

        try:
            cursor = conn.execute("""
                SELECT * FROM apps WHERE addon_key = ?
            """, (addon_key,))

            row = cursor.fetchone()
            if not row:
                return None

            app_dict = dict(row)
            # Deserialize JSON fields
            app_dict['products'] = json.loads(app_dict['products']) if app_dict['products'] else []
            app_dict['hosting'] = json.loads(app_dict['hosting']) if app_dict['hosting'] else []
            app_dict['categories'] = json.loads(app_dict['categories']) if app_dict['categories'] else []
            # Remove SQLite-specific fields
            app_dict.pop('id', None)
            app_dict.pop('created_at', None)
            app_dict.pop('updated_at', None)

            return app_dict

        except sqlite3.Error as e:
            logger.error(f"Error getting app {addon_key}: {str(e)}")
            return None
        finally:
            conn.close()

    def save_versions(self, addon_key: str, versions: List[Version]):
        """
        Save versions for an app.

        Args:
            addon_key: The app's unique key
            versions: List of Version instances
        """
        conn = self._get_connection()

        try:
            # Get app_id
            cursor = conn.execute("SELECT id FROM apps WHERE addon_key = ?", (addon_key,))
            row = cursor.fetchone()
            if not row:
                logger.error(f"App not found: {addon_key}")
                return

            app_id = row[0]

            conn.execute("BEGIN TRANSACTION")

            # Delete existing versions for this app (to avoid v2/v3 API duplicates)
            conn.execute("DELETE FROM versions WHERE addon_key = ?", (addon_key,))

            # Insert versions
            for version in versions:
                conn.execute("""
                    INSERT OR REPLACE INTO versions (
                        app_id, addon_key, version_id, version_name, build_number,
                        release_date, release_notes, summary, compatible_products,
                        compatibility, hosting_type, download_url, file_name, file_size,
                        file_path, downloaded, download_date, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """, (
                    app_id,
                    addon_key,
                    version.version_id,
                    version.version_name,
                    version.build_number,
                    version.release_date,
                    version.release_notes,
                    version.summary,
                    json.dumps(version.compatible_products),
                    version.compatibility,
                    version.hosting_type,
                    version.download_url,
                    version.file_name,
                    version.file_size,
                    version.file_path,
                    1 if version.downloaded else 0,
                    version.download_date
                ))

            # Update app's total_versions count
            conn.execute("""
                UPDATE apps
                SET total_versions = ?, updated_at = datetime('now')
                WHERE addon_key = ?
            """, (len(versions), addon_key))

            conn.commit()
            logger.debug(f"Saved {len(versions)} versions for {addon_key}")

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error saving versions for {addon_key}: {str(e)}")
            raise
        finally:
            conn.close()

    def get_app_versions(self, addon_key: str) -> List[Dict]:
        """
        Get all versions for an app.

        Args:
            addon_key: The app's unique key

        Returns:
            List of version dictionaries
        """
        conn = self._get_connection()

        try:
            cursor = conn.execute("""
                SELECT * FROM versions
                WHERE addon_key = ?
                ORDER BY release_date DESC
            """, (addon_key,))

            versions = []
            for row in cursor.fetchall():
                version_dict = dict(row)
                # Deserialize JSON fields
                version_dict['compatible_products'] = json.loads(version_dict['compatible_products']) if version_dict['compatible_products'] else {}
                # Convert downloaded from integer to boolean
                version_dict['downloaded'] = bool(version_dict['downloaded'])
                # Remove SQLite-specific fields
                version_dict.pop('id', None)
                version_dict.pop('app_id', None)
                version_dict.pop('created_at', None)
                version_dict.pop('updated_at', None)
                versions.append(version_dict)

            return versions

        except sqlite3.Error as e:
            logger.error(f"Error getting versions for {addon_key}: {str(e)}")
            return []
        finally:
            conn.close()

    def update_version_download_status(self, addon_key: str, version_id: str,
                                      downloaded: bool, file_path: Optional[str] = None):
        """
        Update download status for a specific version (THREAD-SAFE).

        Args:
            addon_key: The app's unique key
            version_id: The version ID
            downloaded: Whether the file has been downloaded
            file_path: Local file path (if downloaded)
        """
        conn = self._get_connection()

        try:
            if downloaded and file_path:
                conn.execute("""
                    UPDATE versions
                    SET downloaded = 1,
                        file_path = ?,
                        download_date = datetime('now'),
                        updated_at = datetime('now')
                    WHERE addon_key = ? AND version_id = ?
                """, (file_path, addon_key, str(version_id)))
            else:
                conn.execute("""
                    UPDATE versions
                    SET downloaded = ?,
                        updated_at = datetime('now')
                    WHERE addon_key = ? AND version_id = ?
                """, (1 if downloaded else 0, addon_key, str(version_id)))

            conn.commit()
            logger.debug(f"Updated version {addon_key}:{version_id} downloaded={downloaded}")

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating version status: {str(e)}")
            raise
        finally:
            conn.close()

    def get_apps_count(self, filters: Optional[Dict] = None) -> int:
        """
        Get total number of apps (optionally filtered).

        Args:
            filters: Optional filters (product, search, hosting)

        Returns:
            Count of apps
        """
        conn = self._get_connection()

        # Build dynamic WHERE clause (same as get_all_apps)
        where_clauses = []
        params = []

        if filters:
            if 'product' in filters and filters['product']:
                where_clauses.append("products LIKE ?")
                params.append(f'%"{filters["product"]}"%')

            if 'search' in filters and filters['search']:
                query = filters['search']
                where_clauses.append("""
                    (name LIKE ? OR vendor LIKE ? OR addon_key LIKE ?)
                """)
                params.extend([f'%{query}%', f'%{query}%', f'%{query}%'])

            if 'hosting' in filters and filters['hosting']:
                where_clauses.append("hosting LIKE ?")
                params.append(f'%"{filters["hosting"]}"%')

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        sql = f"SELECT COUNT(*) FROM apps {where_sql}"

        try:
            cursor = conn.execute(sql, params)
            return cursor.fetchone()[0]
        except sqlite3.Error as e:
            logger.error(f"Error getting apps count: {str(e)}")
            return 0
        finally:
            conn.close()

    def get_total_versions_count(self) -> int:
        """Get total number of versions across all apps."""
        conn = self._get_connection()

        try:
            cursor = conn.execute("SELECT COUNT(*) FROM versions")
            return cursor.fetchone()[0]
        except sqlite3.Error as e:
            logger.error(f"Error getting total versions count: {str(e)}")
            return 0
        finally:
            conn.close()

    def get_downloaded_versions_count(self) -> int:
        """Get count of downloaded versions."""
        conn = self._get_connection()

        try:
            cursor = conn.execute("SELECT COUNT(*) FROM versions WHERE downloaded = 1")
            return cursor.fetchone()[0]
        except sqlite3.Error as e:
            logger.error(f"Error getting downloaded versions count: {str(e)}")
            return 0
        finally:
            conn.close()

    def search_apps(self, query: str, product: Optional[str] = None) -> List[Dict]:
        """
        Search apps by query string.

        Args:
            query: Search query
            product: Optional product filter

        Returns:
            List of matching app dictionaries
        """
        filters = {'search': query}
        if product:
            filters['product'] = product

        return self.get_all_apps(filters)

    def save_parent_software_version(self, product_id: str, build_number: int, version_number: str):
        """
        Save a parent software version (e.g., Jira, Confluence version).

        Args:
            product_id: Product identifier (e.g., 'jira', 'confluence')
            build_number: Build number
            version_number: Version string (e.g., '10.0.1')
        """
        conn = self._get_connection()

        try:
            conn.execute("""
                INSERT OR IGNORE INTO parent_software_versions
                (product_id, build_number, version_number)
                VALUES (?, ?, ?)
            """, (product_id, build_number, version_number))
            conn.commit()
            logger.debug(f"Saved parent version: {product_id} {build_number} -> {version_number}")

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error saving parent software version: {str(e)}")
        finally:
            conn.close()

    def save_parent_software_versions_batch(self, product_id: str, versions: List[Dict]):
        """
        Save multiple parent software versions at once.

        Args:
            product_id: Product identifier (e.g., 'jira', 'confluence')
            versions: List of version dicts with 'buildNumber' and 'versionNumber'
        """
        conn = self._get_connection()

        try:
            conn.execute("BEGIN TRANSACTION")

            for version in versions:
                build_number = version.get('buildNumber')
                version_number = version.get('versionNumber')

                if build_number and version_number:
                    conn.execute("""
                        INSERT OR IGNORE INTO parent_software_versions
                        (product_id, build_number, version_number)
                        VALUES (?, ?, ?)
                    """, (product_id, build_number, version_number))

            conn.commit()
            logger.info(f"Saved batch of {len(versions)} parent versions for {product_id}")

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error saving parent software versions batch: {str(e)}")
        finally:
            conn.close()

    def get_parent_software_version(self, product_id: str, build_number: int) -> Optional[str]:
        """
        Get version number for a specific product and build number.

        Args:
            product_id: Product identifier (e.g., 'jira', 'confluence')
            build_number: Build number to look up

        Returns:
            Version string or None if not found
        """
        conn = self._get_connection()

        try:
            cursor = conn.execute("""
                SELECT version_number FROM parent_software_versions
                WHERE product_id = ? AND build_number = ?
            """, (product_id, build_number))

            row = cursor.fetchone()
            return row[0] if row else None

        except sqlite3.Error as e:
            logger.error(f"Error getting parent software version: {str(e)}")
            return None
        finally:
            conn.close()
