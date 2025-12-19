"""Atlassian product definitions for marketplace scraping."""

PRODUCTS = {
    'jira': {
        'api_key': 'jira',
        'name': 'Jira',
        'full_name': 'Jira Software / Service Management / Core'
    },
    'confluence': {
        'api_key': 'confluence',
        'name': 'Confluence',
        'full_name': 'Confluence Server / Data Center'
    },
    'bitbucket': {
        'api_key': 'bitbucket',
        'name': 'Bitbucket',
        'full_name': 'Bitbucket Server / Data Center'
    },
    'bamboo': {
        'api_key': 'bamboo',
        'name': 'Bamboo',
        'full_name': 'Bamboo Server / Data Center'
    },
    'crowd': {
        'api_key': 'crowd',
        'name': 'Crowd',
        'full_name': 'Crowd Server / Data Center'
    }
}

PRODUCT_LIST = list(PRODUCTS.keys())

HOSTING_TYPES = {
    'SERVER': 'server',
    'DATACENTER': 'datacenter',
    'CLOUD': 'cloud'
}

# Only scrape Server and Data Center versions
ALLOWED_HOSTING = [HOSTING_TYPES['SERVER'], HOSTING_TYPES['DATACENTER']]
