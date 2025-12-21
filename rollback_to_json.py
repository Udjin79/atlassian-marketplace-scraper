#!/usr/bin/env python3
"""Rollback SQLite migration and restore JSON files."""

import os
import shutil
import glob
from config import settings


def rollback():
    """Rollback from SQLite to JSON storage."""
    print("\n" + "=" * 70)
    print("Rollback: SQLite → JSON")
    print("=" * 70 + "\n")

    # Find latest backup
    backup_pattern = os.path.join(settings.METADATA_DIR, 'backup_*')
    backups = sorted(glob.glob(backup_pattern), reverse=True)

    if not backups:
        print("❌ Error: No backup directories found!")
        print(f"   Searched in: {settings.METADATA_DIR}")
        print("   Cannot rollback without backup.")
        return False

    latest_backup = backups[0]
    print(f"Found backup: {os.path.basename(latest_backup)}\n")

    # Confirm rollback
    print("This will:")
    print("  1. Delete the SQLite database")
    print("  2. Restore apps.json and versions/ from backup")
    print("  3. You'll need to set USE_SQLITE=False in .env")
    print()

    confirm = input("Proceed with rollback? (yes/no): ").strip().lower()
    if confirm not in ['yes', 'y']:
        print("\n❌ Rollback cancelled")
        return False

    print()

    try:
        # Step 1: Delete SQLite database
        if os.path.exists(settings.DATABASE_PATH):
            backup_db = f"{settings.DATABASE_PATH}.deleted_{os.path.basename(latest_backup).replace('backup_', '')}"
            shutil.move(settings.DATABASE_PATH, backup_db)
            print(f"✓ Moved database to: {backup_db}")
        else:
            print("⚠ No database found to delete")

        # Step 2: Restore apps.json
        backup_apps_json = os.path.join(latest_backup, 'apps.json')
        if os.path.exists(backup_apps_json):
            if os.path.exists(settings.APPS_JSON_PATH):
                os.remove(settings.APPS_JSON_PATH)
            shutil.copy2(backup_apps_json, settings.APPS_JSON_PATH)
            print(f"✓ Restored apps.json")
        else:
            print("⚠ No apps.json in backup")

        # Step 3: Restore versions directory
        backup_versions_dir = os.path.join(latest_backup, 'versions')
        if os.path.exists(backup_versions_dir):
            if os.path.exists(settings.VERSIONS_DIR):
                shutil.rmtree(settings.VERSIONS_DIR)
            shutil.copytree(backup_versions_dir, settings.VERSIONS_DIR)
            version_count = len([f for f in os.listdir(settings.VERSIONS_DIR) if f.endswith('.json')])
            print(f"✓ Restored {version_count} version files")
        else:
            print("⚠ No versions directory in backup")

        # Success
        print("\n" + "=" * 70)
        print("✅ Rollback Complete!")
        print("=" * 70)
        print("\nNext steps:")
        print("1. Set USE_SQLITE=False in .env (or remove the line)")
        print("2. Restart Flask app: python app.py")
        print("3. Verify web UI works with JSON storage")
        print()
        return True

    except Exception as e:
        print(f"\n❌ Rollback failed with error:")
        print(f"   {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run rollback."""
    try:
        success = rollback()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠ Rollback interrupted by user")
        exit(1)


if __name__ == '__main__':
    main()
