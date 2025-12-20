"""Version scraper for fetching app version history."""

from typing import List, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from config import settings
from scraper.marketplace_api import MarketplaceAPI
from scraper.marketplace_api_v3 import MarketplaceAPIv3
from scraper.metadata_store import MetadataStore
from scraper.filters import filter_by_date, filter_by_hosting
from models.version import Version
from utils.logger import get_logger

logger = get_logger('scraper')


class VersionScraper:
    """Scrapes version information for marketplace apps."""

    def __init__(self, api: Optional[MarketplaceAPI] = None,
                 api_v3: Optional[MarketplaceAPIv3] = None,
                 store: Optional[MetadataStore] = None):
        """
        Initialize version scraper.

        Args:
            api: MarketplaceAPI instance (v2)
            api_v3: MarketplaceAPIv3 instance (for compatibility)
            store: MetadataStore instance
        """
        self.api = api or MarketplaceAPI()
        self.store = store or MetadataStore()
        self.api_v3 = api_v3 or MarketplaceAPIv3(metadata_store=self.store)

    def scrape_all_app_versions(self, filter_date: bool = True,
                                filter_hosting: bool = True,
                                max_workers: int = 5,
                                product_filter: Optional[str] = None):
        """
        Scrape versions for all apps in the metadata store (parallel).

        Args:
            filter_date: Whether to filter by date (last year)
            filter_hosting: Whether to filter by hosting type (server/datacenter)
            max_workers: Number of concurrent workers (default: 5)
            product_filter: Optional product filter (e.g., 'crowd', 'jira')
        """
        # Get apps with optional product filter
        filters = {'product': product_filter} if product_filter else None
        apps = self.store.get_all_apps(filters)

        if not apps:
            print("❌ No apps found in metadata store. Run app scraper first.")
            return

        print(f"🔄 Starting parallel version scraping for {len(apps)} apps ({max_workers} workers)...")
        logger.info(f"Starting parallel version scraping for {len(apps)} apps with {max_workers} workers")

        # Thread-safe counters
        total_versions = 0
        completed_count = 0
        failed_apps = []
        lock = Lock()

        def scrape_app(app_info):
            """Scrape versions for a single app (thread-safe)."""
            nonlocal total_versions, completed_count, failed_apps

            idx, app = app_info
            addon_key = app.get('addon_key')
            app_name = app.get('name', addon_key)[:40]

            try:
                versions = self.scrape_app_versions(
                    addon_key,
                    filter_date=filter_date,
                    filter_hosting=filter_hosting
                )

                if versions:
                    self.store.save_versions(addon_key, versions)
                    with lock:
                        total_versions += len(versions)
                        completed_count += 1
                        print(f"{completed_count}/{len(apps)} ✓ {app_name}: Found {len(versions)} versions → Saved (Total: {total_versions})")
                    logger.info(f"Saved {len(versions)} versions for {addon_key}")
                    return ('success', addon_key, len(versions))
                else:
                    with lock:
                        completed_count += 1
                        print(f"{completed_count}/{len(apps)} ○ {app_name}: No versions found (after filtering)")
                    logger.debug(f"No versions found for {addon_key}")
                    return ('no_versions', addon_key, 0)

            except Exception as e:
                with lock:
                    completed_count += 1
                    print(f"{completed_count}/{len(apps)} ✗ {app_name}: Error - {str(e)}")
                logger.error(f"Error scraping versions for {addon_key}: {str(e)}")
                return ('error', addon_key, str(e))

        # Process apps in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            futures = {executor.submit(scrape_app, (idx, app)): app
                      for idx, app in enumerate(apps, 1)}

            # Wait for completion
            for future in as_completed(futures):
                status, addon_key, result = future.result()
                if status == 'error':
                    failed_apps.append(addon_key)

        print(f"\n✅ Version scraping complete!")
        print(f"   Total versions collected: {total_versions}")
        print(f"   Average per app: {total_versions / len(apps):.1f}")

        if failed_apps:
            print(f"   ⚠️ Failed apps: {len(failed_apps)}")
            logger.warning(f"Failed to scrape versions for {len(failed_apps)} apps")

    def scrape_app_versions(self, addon_key: str,
                           filter_date: bool = True,
                           filter_hosting: bool = True) -> List[Version]:
        """
        Scrape versions for a specific app using v3 API (with compatibility).

        Args:
            addon_key: The app's unique key
            filter_date: Whether to filter by date
            filter_hosting: Whether to filter by hosting type

        Returns:
            List of Version instances
        """
        try:
            versions = []

            # Get appSoftwareIds from v3 API
            app_software_list = self.api_v3.get_app_software_ids(addon_key)

            if not app_software_list:
                logger.debug(f"{addon_key}: No appSoftwareIds found in v3 API")
                return []

            logger.debug(f"{addon_key}: Found {len(app_software_list)} appSoftwareIds")

            # Fetch versions for each hosting type
            for app_software in app_software_list:
                app_software_id = app_software.get('appSoftwareId')
                hosting_type = app_software.get('hosting')

                if not app_software_id or not hosting_type:
                    continue

                # Skip cloud versions if filtering by hosting
                if filter_hosting and hosting_type == 'cloud':
                    continue

                # Get versions from v3 API
                v3_versions = self.api_v3.get_all_app_versions_v3(app_software_id)
                logger.debug(f"{addon_key}: Got {len(v3_versions)} {hosting_type} versions from v3 API")

                # Convert to Version objects
                for v3_version in v3_versions:
                    try:
                        # Format compatibility
                        compatibilities = v3_version.get('compatibilities', [])
                        compatibility_string = None

                        if compatibilities:
                            # Use first compatibility (usually there's only one)
                            compat = compatibilities[0]
                            # Pass hosting type to format correctly (Data Center vs Server)
                            compatibility_string = self.api_v3.format_compatibility_string(compat, hosting_type)

                        # Create Version object from v3 API response
                        version = Version.from_v3_api_response(
                            addon_key=addon_key,
                            api_data=v3_version,
                            compatibility_string=compatibility_string
                        )

                        # Set hosting type
                        version.hosting_type = hosting_type

                        versions.append(version)

                    except Exception as e:
                        logger.error(f"Error parsing v3 version for {addon_key}: {str(e)}")
                        continue

            if not versions:
                logger.debug(f"{addon_key}: No versions found")
                return []

            logger.debug(f"{addon_key}: Total {len(versions)} versions before filtering")

            # Log first few version dates for debugging
            if versions:
                sample_versions = versions[:3]
                sample_info = [f"{v.version_name} ({v.release_date}, hosting={v.hosting_type})"
                              for v in sample_versions]
                logger.debug(f"{addon_key}: Sample versions: {', '.join(sample_info)}")

            # Apply date filter
            if filter_date:
                versions_dicts = [v.to_dict() for v in versions]
                initial_count = len(versions_dicts)
                versions_dicts = filter_by_date(versions_dicts)
                versions = [Version.from_dict(v) for v in versions_dicts]
                logger.debug(f"{addon_key}: After date filter: {len(versions)}/{initial_count} versions")

            if len(versions) == 0:
                logger.warning(f"{addon_key}: All versions were filtered out!")

            return versions

        except Exception as e:
            logger.error(f"Error scraping versions for {addon_key}: {str(e)}")
            return []

    def update_app_versions(self, addon_key: str):
        """
        Update versions for a specific app.

        Args:
            addon_key: The app's unique key
        """
        print(f"🔄 Updating versions for {addon_key}...")

        versions = self.scrape_app_versions(addon_key)

        if versions:
            self.store.save_versions(addon_key, versions)
            print(f"✅ Updated {len(versions)} versions for {addon_key}")
        else:
            print(f"⚠️ No versions found for {addon_key}")

    def get_versions_summary(self):
        """Print summary of versions in metadata store."""
        total_versions = self.store.get_total_versions_count()
        downloaded = self.store.get_downloaded_versions_count()
        pending = total_versions - downloaded

        print(f"\n📊 Versions Summary:")
        print(f"   Total versions: {total_versions}")
        print(f"   Downloaded: {downloaded}")
        print(f"   Pending: {pending}")
        print(f"   Download progress: {(downloaded/total_versions*100):.1f}%" if total_versions > 0 else "0%")
