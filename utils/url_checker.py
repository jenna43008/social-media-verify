"""URL resolution and validation utilities."""

import re
from urllib.parse import urlparse

import requests


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

TIMEOUT = 15


def validate_url_format(url: str) -> tuple[bool, str]:
    """Validate that a string is a well-formed URL.

    Returns (is_valid, message).
    """
    if not url or not url.strip():
        return False, "URL is empty."

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False, "URL is not valid. Must include a domain (e.g., https://linkedin.com/company/example)."

    # Basic domain check
    domain_pattern = re.compile(
        r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$"
    )
    hostname = parsed.hostname or ""
    if not domain_pattern.match(hostname):
        return False, f"Invalid domain: {hostname}"

    return True, url


def check_url_resolves(url: str) -> dict:
    """Check whether a URL resolves successfully.

    Returns a dict with:
      - resolved: bool
      - status_code: int or None
      - final_url: str or None (after redirects)
      - error: str or None
      - html: str or None (page content for further analysis)
    """
    is_valid, result = validate_url_format(url)
    if not is_valid:
        return {
            "resolved": False,
            "status_code": None,
            "final_url": None,
            "error": result,
            "html": None,
        }

    url = result  # normalized URL

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        resolved = response.status_code < 400
        return {
            "resolved": resolved,
            "status_code": response.status_code,
            "final_url": response.url,
            "error": None if resolved else f"HTTP {response.status_code}",
            "html": response.text if resolved else None,
        }

    except requests.exceptions.SSLError:
        return {
            "resolved": False,
            "status_code": None,
            "final_url": None,
            "error": "SSL certificate error — the site's certificate could not be verified.",
            "html": None,
        }
    except requests.exceptions.ConnectionError:
        return {
            "resolved": False,
            "status_code": None,
            "final_url": None,
            "error": "Connection failed — the server could not be reached.",
            "html": None,
        }
    except requests.exceptions.Timeout:
        return {
            "resolved": False,
            "status_code": None,
            "final_url": None,
            "error": f"Request timed out after {TIMEOUT} seconds.",
            "html": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "resolved": False,
            "status_code": None,
            "final_url": None,
            "error": str(e),
            "html": None,
        }


def detect_platform(url: str) -> str | None:
    """Detect which social media platform a URL belongs to."""
    url_lower = url.lower()
    if "linkedin.com" in url_lower:
        return "linkedin"
    if "facebook.com" in url_lower or "fb.com" in url_lower:
        return "facebook"
    if "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    if "instagram.com" in url_lower:
        return "instagram"
    return "other"
