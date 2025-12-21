"""App scraper for discovering marketplace apps."""

from typing import List, Optional
from tqdm import tqdm
from config import settings
from config.products import PRODUCT_LIST, PRODUCTS
from scraper.marketplace_api import MarketplaceAPI
from scraper.metadata_store import MetadataStore
from models.app import App
from utils.checkpoint import save_checkpoint, load_checkpoint, clear_checkpoint
from utils.logger import get_logger

logger = get_logger('scraper')


class AppScraper:
    """Scrapes apps from Atlassian Marketplace."""

    def __init__(self, api: Optional[MarketplaceAPI] = None,
                 store: Optional[MetadataStore] = None):
        """
        Initialize app scraper.

        Args:
            api: MarketplaceAPI instance
            store: MetadataStore instance
        """
        self.api = api or MarketplaceAPI()
        self.store = store or MetadataStore()
        self.checkpoint_interval = 100  # Save every 100 apps

    def scrape_all_products(self, products: Optional[List[str]] = None,
                           resume: bool = True):
        """
        Scrape apps for all products.

        Args:
            products: List of product keys (default: all products)
            resume: Whether to resume from checkpoint
        """
        if products is None:
            products = PRODUCT_LIST

        print(f"[*] Starting app scraping for {len(products)} products: {', '.join(products)}")
        logger.info(f"Starting app scraping for products: {products}")

        # Try to resume from checkpoint
        state = None
        if resume:
            state = load_checkpoint()
            if state:
                print(f"[*] Resuming from checkpoint: {state.get('apps_processed', 0)} apps processed")
                logger.info(f"Resuming from checkpoint: {state}")

        if state is None:
            state = {
                'product_index': 0,
                'current_product': None,
                'app_offset': 0,
                'apps_processed': 0,
                'apps_collected': []
            }

        # Start from saved product index
        for product_idx in range(state['product_index'], len(products)):
            product = products[product_idx]
            state['current_product'] = product
            state['product_index'] = product_idx

            # Reset offset if switching products
            if product_idx > state.get('last_product_index', -1):
                state['app_offset'] = 0
                state['last_product_index'] = product_idx

            print(f"\n[*] Scraping {PRODUCTS[product]['name']} apps...")
            apps_for_product = self.scrape_product_apps(product, state)

            print(f"[OK] Found {len(apps_for_product)} {product} apps")
            logger.info(f"Completed {product}: {len(apps_for_product)} apps")

            # Move to next product
            state['app_offset'] = 0

        # Save all collected apps
        if state.get('apps_collected'):
            print(f"\n[*] Saving {len(state['apps_collected'])} apps to metadata store...")
            self.store.save_apps_batch(state['apps_collected'])

        # Clear checkpoint on successful completion
        clear_checkpoint()

        total = self.store.get_apps_count()
        print(f"\n[OK] Scraping complete! Total apps: {total}")
        logger.info(f"App scraping completed. Total apps: {total}")

    def scrape_product_apps(self, product: str, state: dict) -> List[App]:
        """
        Scrape apps for a specific product.

        Args:
            product: Product key (jira, confluence, etc.)
            state: Checkpoint state dictionary

        Returns:
            List of App instances
        """
        apps = []
        offset = state.get('app_offset', 0)
        batch_size = settings.SCRAPER_BATCH_SIZE

        # First, get total count (approximate)
        initial_response = self.api.search_apps(
            hosting='server',
            application=product,
            offset=0,
            limit=1
        )

        # Try to determine total (API might not provide this)
        print(f"   Fetching {product} apps (Server/Data Center only)...")

        # Progress bar (we don't know total, so use unknown total)
        with tqdm(desc=f"   {product}", unit="app", initial=offset) as pbar:
            while True:
                try:
                    # Search for apps
                    response = self.api.search_apps(
                        hosting='server',
                        application=product,
                        offset=offset,
                        limit=batch_size
                    )

                    if not response or '_embedded' not in response:
                        break

                    addons = response['_embedded'].get('addons', [])
                    if not addons:
                        break

                    # Process apps
                    for addon_data in addons:
                        try:
                            # Pass product and hosting context to capture metadata
                            app = App.from_api_response(addon_data, product=product, hosting_type='server')
                            apps.append(app)
                            state['apps_collected'].append(app)
                            state['apps_processed'] += 1

                            pbar.update(1)

                        except Exception as e:
                            logger.error(f"Error processing app {addon_data.get('key', 'unknown')}: {str(e)}")
                            continue

                    # Save checkpoint periodically
                    if state['apps_processed'] % self.checkpoint_interval == 0:
                        save_checkpoint(state)
                        logger.debug(f"Checkpoint saved: {state['apps_processed']} apps processed")

                    # Check if there are more pages
                    links = response.get('_links', {})
                    if 'next' not in links:
                        break

                    offset += len(addons)
                    state['app_offset'] = offset

                except Exception as e:
                    logger.error(f"Error scraping {product} at offset {offset}: {str(e)}")
                    print(f"   [WARNING] Error at offset {offset}, continuing...")
                    offset += batch_size
                    state['app_offset'] = offset
                    continue

        return apps

    def scrape_single_app(self, addon_key: str) -> Optional[App]:
        """
        Scrape a single app by its key.

        Args:
            addon_key: The app's unique key

        Returns:
            App instance or None
        """
        try:
            app_data = self.api.get_app_details(addon_key)
            if app_data:
                # Note: Product unknown when fetching single app, but hosting assumed server
                app = App.from_api_response(app_data, hosting_type='server')
                self.store.save_app(app)
                logger.info(f"Scraped single app: {addon_key}")
                return app
        except Exception as e:
            logger.error(f"Error scraping app {addon_key}: {str(e)}")

        return None

    def update_app_details(self, addon_key: str):
        """
        Update an existing app's details.

        Args:
            addon_key: The app's unique key
        """
        app = self.scrape_single_app(addon_key)
        if app:
            print(f"[OK] Updated app: {app.name} ({addon_key})")
        else:
            print(f"[ERROR] Failed to update app: {addon_key}")
