#!/usr/bin/env python
"""Script to migrate existing SQLite database to add missing columns."""

import sqlite3
import os
from config import settings
from utils.logger import setup_logging

setup_logging()

def migrate_database():
    """Add missing columns to existing database."""
    db_path = settings.DATABASE_PATH
    
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        print("Database will be created automatically on first run.")
        return
    
    print(f"Migrating database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    try:
        # Check if compatibility column exists
        cursor = conn.execute("PRAGMA table_info(versions)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'compatibility' not in columns:
            print("Adding compatibility column to versions table...")
            conn.execute("ALTER TABLE versions ADD COLUMN compatibility TEXT")
            conn.commit()
            print("✓ Migration completed successfully!")
        else:
            print("✓ Database already has compatibility column")
            
    except sqlite3.Error as e:
        print(f"✗ Migration error: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    migrate_database()

