#!/usr/bin/env python
"""Test v3 API compatibility extraction and display."""

from scraper.marketplace_api_v3 import MarketplaceAPIv3
from scraper.metadata_store import MetadataStore
from models.version import Version

def test_v3_compatibility():
    """Test fetching and storing compatibility information."""

    addon_key = 'com.alphaserve.confluence.authplugin'

    print(f"Testing v3 API compatibility for: {addon_key}\n")
    print("="*80)

    # Initialize metadata store for database caching
    store = MetadataStore()

    # Step 1: Get appSoftwareIds
    api_v3 = MarketplaceAPIv3(metadata_store=store)

    print("\n1. Getting appSoftwareIds...")
    app_software_list = api_v3.get_app_software_ids(addon_key)

    if not app_software_list:
        print("✗ No appSoftwareIds found")
        return

    print(f"✓ Found {len(app_software_list)} appSoftwareIds:")
    for item in app_software_list:
        print(f"  - {item['hosting']}: {item['appSoftwareId']}")

    # Use datacenter version
    datacenter_app = next((a for a in app_software_list if a['hosting'] == 'datacenter'), None)
    if not datacenter_app:
        print("✗ No datacenter version found")
        return

    app_software_id = datacenter_app['appSoftwareId']
    hosting_type = datacenter_app['hosting']

    # Step 2: Get versions from v3 API
    print(f"\n2. Fetching versions from v3 API...")
    v3_versions = api_v3.get_all_app_versions_v3(app_software_id)

    print(f"✓ Found {len(v3_versions)} versions")

    # Step 3: Process first few versions
    print(f"\n3. Processing versions with compatibility...")

    versions_to_save = []

    for v3_version in v3_versions[:5]:  # Test with first 5
        # Format compatibility
        compatibilities = v3_version.get('compatibilities', [])
        compatibility_string = None

        if compatibilities:
            # Use first compatibility (usually there's only one)
            compat = compatibilities[0]
            compatibility_string = api_v3.format_compatibility_string(compat, hosting_type)

        # Create Version object from v3 API response
        version = Version.from_v3_api_response(
            addon_key=addon_key,
            api_data=v3_version,
            compatibility_string=compatibility_string
        )

        # Set hosting type
        version.hosting_type = hosting_type

        versions_to_save.append(version)

        print(f"\n  Version: {version.version_name}")
        print(f"    Build: {version.build_number}")
        print(f"    Released: {version.release_date}")
        print(f"    Compatibility: {version.compatibility or 'N/A'}")
        print(f"    Hosting: {version.hosting_type}")
        print(f"    Download URL: {version.download_url[:60] if version.download_url else 'N/A'}...")

    # Step 4: Save to database
    print(f"\n4. Saving to database...")
    store.save_versions(addon_key, versions_to_save)
    print(f"✓ Saved {len(versions_to_save)} versions")

    # Step 5: Verify from database
    print(f"\n5. Verifying from database...")
    saved_versions = store.get_app_versions(addon_key)

    print(f"✓ Database has {len(saved_versions)} total versions")
    print(f"\nFirst 3 versions from database:")
    for v in saved_versions[:3]:
        print(f"  - {v['version_name']}: {v.get('compatibility', 'N/A')}")

    print("\n" + "="*80)
    print("✓ Test complete! Check the web UI at /apps/" + addon_key)

if __name__ == '__main__':
    test_v3_compatibility()
