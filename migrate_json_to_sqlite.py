#!/usr/bin/env python3
"""Migrate JSON metadata to SQLite database."""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from tqdm import tqdm
from config import settings
from scraper.metadata_store_sqlite import MetadataStoreSQLite
from models.app import App
from models.version import Version


class JSONToSQLiteMigrator:
    """Migrates JSON-based metadata to SQLite database."""

    def __init__(self):
        self.db_path = settings.DATABASE_PATH
        self.apps_json = settings.APPS_JSON_PATH
        self.versions_dir = settings.VERSIONS_DIR
        self.store = None

    def run(self):
        """Execute full migration."""
        print("\n" + "=" * 70)
        print("JSON → SQLite Migration for AtlassianMarketplaceScraper")
        print("=" * 70 + "\n")

        # Check if JSON files exist
        if not os.path.exists(self.apps_json):
            print(f"❌ Error: apps.json not found at {self.apps_json}")
            print("   Nothing to migrate. Run the scraper first.")
            return

        # Step 1: Create database
        print("Step 1: Creating SQLite database...")
        self._create_database()

        # Step 2: Migrate apps
        print("\nStep 2: Migrating apps from JSON...")
        apps_migrated = self._migrate_apps()

        # Step 3: Migrate versions
        print("\nStep 3: Migrating versions from JSON...")
        versions_migrated = self._migrate_versions()

        # Step 4: Verify integrity
        print("\nStep 4: Verifying migration integrity...")
        self._verify_migration(apps_migrated, versions_migrated)

        # Step 5: Backup JSON files
        print("\nStep 5: Backing up JSON files...")
        self._backup_json_files()

        # Summary
        print("\n" + "=" * 70)
        print("✅ Migration Complete!")
        print("=" * 70)
        print(f"   Apps migrated:     {apps_migrated:,}")
        print(f"   Versions migrated: {versions_migrated:,}")
        print(f"   Database location: {self.db_path}")
        print("\nNext steps:")
        print("1. Set USE_SQLITE=True in .env file")
        print("2. Restart Flask app: python app.py")
        print("3. Verify web UI works correctly")
        print("4. Run downloader to test concurrent writes")
        print("\nTo rollback: python rollback_to_json.py\n")

    def _create_database(self):
        """Create SQLite database with schema."""
        # Delete existing database if present
        if os.path.exists(self.db_path):
            backup_path = f"{self.db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            print(f"   Backing up existing database to {backup_path}")
            shutil.copy2(self.db_path, backup_path)
            os.remove(self.db_path)

        # Initialize new database
        self.store = MetadataStoreSQLite(self.db_path)
        print(f"   ✓ Database created at {self.db_path}")

    def _migrate_apps(self) -> int:
        """
        Migrate apps.json to apps table.

        Returns:
            Number of apps migrated
        """
        if not os.path.exists(self.apps_json):
            print("   ⚠ No apps.json found, skipping...")
            return 0

        # Read JSON file
        with open(self.apps_json, 'r', encoding='utf-8') as f:
            apps_data = json.load(f)

        if not apps_data:
            print("   ⚠ apps.json is empty, skipping...")
            return 0

        print(f"   Found {len(apps_data)} apps in JSON file")

        # Convert to App objects and save in batches
        batch_size = 100
        apps_batch = []
        total_migrated = 0

        with tqdm(total=len(apps_data), desc="   Migrating apps", unit="app") as pbar:
            for app_data in apps_data:
                try:
                    # Create App object from dict
                    app = App.from_dict(app_data)
                    apps_batch.append(app)

                    # Save batch when it reaches batch_size
                    if len(apps_batch) >= batch_size:
                        self.store.save_apps_batch(apps_batch)
                        total_migrated += len(apps_batch)
                        pbar.update(len(apps_batch))
                        apps_batch = []

                except Exception as e:
                    print(f"\n   ⚠ Error migrating app {app_data.get('addon_key', 'unknown')}: {str(e)}")
                    pbar.update(1)

            # Save remaining apps
            if apps_batch:
                self.store.save_apps_batch(apps_batch)
                total_migrated += len(apps_batch)
                pbar.update(len(apps_batch))

        print(f"   ✓ Migrated {total_migrated} apps successfully")
        return total_migrated

    def _migrate_versions(self) -> int:
        """
        Migrate all version files to versions table.

        Returns:
            Number of versions migrated
        """
        if not os.path.exists(self.versions_dir):
            print("   ⚠ No versions directory found, skipping...")
            return 0

        # Find all version files
        version_files = [f for f in os.listdir(self.versions_dir) if f.endswith('_versions.json')]

        if not version_files:
            print("   ⚠ No version files found, skipping...")
            return 0

        print(f"   Found {len(version_files)} version files")

        total_migrated = 0

        with tqdm(total=len(version_files), desc="   Migrating versions", unit="file") as pbar:
            for version_file in version_files:
                try:
                    # Extract addon_key from filename
                    addon_key = version_file.replace('_versions.json', '')

                    # Read version file
                    file_path = os.path.join(self.versions_dir, version_file)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        versions_data = json.load(f)

                    if not versions_data:
                        pbar.update(1)
                        continue

                    # Convert to Version objects
                    versions = []
                    for version_data in versions_data:
                        try:
                            version = Version.from_dict(version_data)
                            versions.append(version)
                        except Exception as e:
                            print(f"\n   ⚠ Error parsing version: {str(e)}")

                    # Save versions
                    if versions:
                        self.store.save_versions(addon_key, versions)
                        total_migrated += len(versions)

                    pbar.update(1)

                except Exception as e:
                    print(f"\n   ⚠ Error migrating {version_file}: {str(e)}")
                    pbar.update(1)

        print(f"   ✓ Migrated {total_migrated} versions successfully")
        return total_migrated

    def _verify_migration(self, apps_expected: int, versions_expected: int):
        """
        Verify data integrity after migration.

        Args:
            apps_expected: Expected number of apps
            versions_expected: Expected number of versions
        """
        # Count apps in database
        apps_actual = self.store.get_apps_count()
        print(f"   Apps:     Expected {apps_expected:,}, Found {apps_actual:,}", end="")
        if apps_actual == apps_expected:
            print(" ✓")
        else:
            print(" ⚠ MISMATCH!")

        # Count versions in database
        versions_actual = self.store.get_total_versions_count()
        print(f"   Versions: Expected {versions_expected:,}, Found {versions_actual:,}", end="")
        if versions_actual == versions_expected:
            print(" ✓")
        else:
            print(" ⚠ MISMATCH!")

        # Spot check: Get 5 random apps and verify their versions
        sample_apps = self.store.get_all_apps(limit=5)
        if sample_apps:
            print(f"\n   Spot-checking {len(sample_apps)} random apps...")
            all_good = True
            for app in sample_apps:
                addon_key = app['addon_key']
                db_versions = self.store.get_app_versions(addon_key)
                db_count = len(db_versions)
                expected_count = app.get('total_versions', 0)

                status = "✓" if db_count == expected_count else "⚠"
                print(f"   {status} {addon_key}: {db_count} versions (expected {expected_count})")

                if db_count != expected_count:
                    all_good = False

            if all_good:
                print("   ✓ All spot checks passed")
        else:
            print("   ⚠ No apps found for spot checking")

    def _backup_json_files(self):
        """Backup JSON files to timestamped directory."""
        # Create backup directory
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = os.path.join(settings.METADATA_DIR, f'backup_{timestamp}')
        os.makedirs(backup_dir, exist_ok=True)

        # Backup apps.json
        if os.path.exists(self.apps_json):
            shutil.copy2(self.apps_json, os.path.join(backup_dir, 'apps.json'))
            print(f"   ✓ Backed up apps.json")

        # Backup versions directory
        if os.path.exists(self.versions_dir):
            backup_versions_dir = os.path.join(backup_dir, 'versions')
            shutil.copytree(self.versions_dir, backup_versions_dir)
            version_count = len([f for f in os.listdir(backup_versions_dir) if f.endswith('.json')])
            print(f"   ✓ Backed up {version_count} version files")

        print(f"   ✓ Backup saved to: {backup_dir}")
        print(f"\n   Note: JSON files NOT deleted (kept as safety backup)")
        print(f"   You can manually delete them after verifying SQLite works")


def main():
    """Run migration."""
    migrator = JSONToSQLiteMigrator()
    try:
        migrator.run()
    except KeyboardInterrupt:
        print("\n\n⚠ Migration interrupted by user")
        print("   Database may be in incomplete state")
        print("   Run migration again or use rollback_to_json.py")
    except Exception as e:
        print(f"\n\n❌ Migration failed with error:")
        print(f"   {str(e)}")
        import traceback
        traceback.print_exc()
        print("\n   Use rollback_to_json.py to restore JSON files")


if __name__ == '__main__':
    main()
