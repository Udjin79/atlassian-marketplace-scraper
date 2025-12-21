#!/usr/bin/env python
"""Fix relative marketplace URLs in the database to be absolute URLs."""

import sqlite3
from config import settings

def fix_marketplace_urls():
    """Update all relative marketplace URLs to absolute URLs."""
    db_path = settings.DATABASE_PATH

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Get all apps with relative URLs
        cursor.execute("""
            SELECT addon_key, marketplace_url
            FROM apps
            WHERE marketplace_url IS NOT NULL
            AND marketplace_url LIKE '/%'
        """)

        apps_to_update = cursor.fetchall()

        print(f"Found {len(apps_to_update)} apps with relative URLs")

        if apps_to_update:
            # Update each app
            updated = 0
            for addon_key, old_url in apps_to_update:
                new_url = f'https://marketplace.atlassian.com{old_url}'

                cursor.execute("""
                    UPDATE apps
                    SET marketplace_url = ?, updated_at = datetime('now')
                    WHERE addon_key = ?
                """, (new_url, addon_key))

                updated += 1
                if updated % 100 == 0:
                    print(f"  Updated {updated}/{len(apps_to_update)} apps...")

            conn.commit()
            print(f"\n✓ Successfully updated {updated} marketplace URLs")
        else:
            print("✓ All marketplace URLs are already absolute")

    except Exception as e:
        conn.rollback()
        print(f"✗ Error: {e}")
        raise

    finally:
        conn.close()

if __name__ == '__main__':
    print("Fixing marketplace URLs in database...\n")
    fix_marketplace_urls()
    print("\nDone!")
