#!/usr/bin/env python
"""Add compatibility column to versions table."""

import sqlite3
from config import settings

def add_compatibility_column():
    """Add compatibility column to the versions table."""
    db_path = settings.DATABASE_PATH

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(versions)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'compatibility' not in columns:
            print("Adding 'compatibility' column to versions table...")

            cursor.execute("""
                ALTER TABLE versions
                ADD COLUMN compatibility TEXT
            """)

            conn.commit()
            print("✓ Successfully added 'compatibility' column")
        else:
            print("✓ 'compatibility' column already exists")

    except Exception as e:
        conn.rollback()
        print(f"✗ Error: {e}")
        raise

    finally:
        conn.close()

if __name__ == '__main__':
    print("Adding compatibility column to database...\n")
    add_compatibility_column()
    print("\nDone!")
