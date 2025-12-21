// Main JavaScript for Atlassian Marketplace Scraper

// CSRF Token Helper
function getCSRFToken() {
    return document.querySelector('meta[name="csrf-token"]').getAttribute('content');
}

// Enhanced fetch with CSRF token for POST/PUT/DELETE requests
function fetchWithCSRF(url, options = {}) {
    // Add CSRF token to headers for non-GET requests
    if (!options.method || options.method.toUpperCase() !== 'GET') {
        options.headers = options.headers || {};
        options.headers['X-CSRFToken'] = getCSRFToken();
    }
    return fetch(url, options);
}

document.addEventListener('DOMContentLoaded', function() {
    // Auto-submit search form on product change
    const productSelect = document.querySelector('select[name="product"]');
    if (productSelect) {
        productSelect.addEventListener('change', function() {
            this.form.submit();
        });
    }

    // Add copy-to-clipboard functionality for code blocks
    const codeBlocks = document.querySelectorAll('code');
    codeBlocks.forEach(function(codeBlock) {
        if (codeBlock.textContent.length > 20) {
            codeBlock.style.cursor = 'pointer';
            codeBlock.title = 'Click to copy';

            codeBlock.addEventListener('click', function() {
                navigator.clipboard.writeText(this.textContent).then(function() {
                    // Show copied feedback
                    const originalText = codeBlock.textContent;
                    codeBlock.textContent = 'Copied!';
                    setTimeout(function() {
                        codeBlock.textContent = originalText;
                    }, 1000);
                });
            });
        }
    });

    // Refresh stats every 30 seconds on dashboard
    if (window.location.pathname === '/') {
        setInterval(refreshStats, 30000);
    }
});

// Refresh statistics on dashboard
function refreshStats() {
    fetch('/api/stats')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Update stats on page if elements exist
                const stats = data.stats;

                // Update total apps
                updateElement('.card-body h2:first-of-type', stats.total_apps);

                // Update total versions
                const versionElements = document.querySelectorAll('.card-body h2');
                if (versionElements.length > 1) {
                    versionElements[1].textContent = stats.total_versions;
                }

                // Update downloaded count
                if (versionElements.length > 2) {
                    versionElements[2].textContent = stats.downloaded_versions;
                }

                // Update storage
                if (versionElements.length > 3) {
                    const storageGB = stats.storage.total_gb;
                    const storageMB = stats.storage.total_mb;
                    if (storageGB >= 1.0) {
                        versionElements[3].textContent = storageGB.toFixed(2) + ' GB';
                    } else {
                        versionElements[3].textContent = Math.round(storageMB) + ' MB';
                    }
                }
            }
        })
        .catch(error => console.error('Error refreshing stats:', error));
}

function updateElement(selector, value) {
    const element = document.querySelector(selector);
    if (element) {
        element.textContent = value;
    }
}

// Utility: Format file size
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// Utility: Format date
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}
