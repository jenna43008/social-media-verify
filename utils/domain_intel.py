"""Domain intelligence: WHOIS age, DNS records, historical DNS, website scraping for social links."""

import re
import socket
from datetime import date, datetime
from urllib.parse import urlparse

import requests
import whois
from bs4 import BeautifulSoup

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


def get_domain_age(domain: str) -> dict:
    """Look up WHOIS data and return domain registration info.

    Returns:
        {
            "creation_date": date or None,
            "expiration_date": date or None,
            "registrar": str or None,
            "age_days": int or None,
            "error": str or None,
        }
    """
    result = {
        "creation_date": None,
        "expiration_date": None,
        "registrar": None,
        "age_days": None,
        "error": None,
    }

    try:
        w = whois.whois(domain)

        creation = w.creation_date
        if isinstance(creation, list):
            creation = creation[0]
        if isinstance(creation, datetime):
            creation = creation.date()
        if creation:
            result["creation_date"] = creation
            result["age_days"] = (date.today() - creation).days

        expiration = w.expiration_date
        if isinstance(expiration, list):
            expiration = expiration[0]
        if isinstance(expiration, datetime):
            expiration = expiration.date()
        if expiration:
            result["expiration_date"] = expiration

        result["registrar"] = w.registrar

    except Exception as e:
        result["error"] = str(e)

    return result


def scrape_website_social_links(domain: str) -> dict:
    """Scrape the company's own website to find social media links.

    This is the most reliable discovery method — companies link to their
    own social profiles from their homepage/footer.

    Returns:
        {
            "social_links": {"linkedin": "url", "facebook": "url", ...},
            "website_reachable": bool,
            "website_title": str,
            "error": str or None,
        }
    """
    result = {
        "social_links": {},
        "website_reachable": False,
        "website_title": "",
        "error": None,
    }

    url = f"https://{domain}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code >= 400:
            # Try http
            resp = requests.get(
                f"http://{domain}", headers=HEADERS, timeout=TIMEOUT, allow_redirects=True
            )
    except Exception:
        try:
            resp = requests.get(
                f"http://{domain}", headers=HEADERS, timeout=TIMEOUT, allow_redirects=True
            )
        except Exception as e:
            result["error"] = f"Website unreachable: {e}"
            return result

    if resp.status_code >= 400:
        result["error"] = f"HTTP {resp.status_code}"
        return result

    result["website_reachable"] = True
    soup = BeautifulSoup(resp.text, "lxml")

    if soup.title and soup.title.string:
        result["website_title"] = soup.title.string.strip()

    # Social media link patterns
    social_patterns = {
        "linkedin": [r"linkedin\.com/company/", r"linkedin\.com/in/"],
        "facebook": [r"facebook\.com/", r"fb\.com/"],
        "twitter": [r"twitter\.com/", r"x\.com/"],
        "instagram": [r"instagram\.com/"],
        "youtube": [r"youtube\.com/", r"youtu\.be/"],
        "github": [r"github\.com/"],
        "tiktok": [r"tiktok\.com/@"],
    }

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href.startswith(("http://", "https://")):
            continue

        href_lower = href.lower()
        for platform, patterns in social_patterns.items():
            if platform not in result["social_links"]:
                for pattern in patterns:
                    if re.search(pattern, href_lower):
                        # Clean the URL
                        clean = href.split("?")[0].rstrip("/")
                        result["social_links"][platform] = clean
                        break

    return result


def check_dns_records(domain: str) -> dict:
    """Basic DNS check — does the domain resolve?"""
    result = {"resolves": False, "ip_addresses": [], "has_mx": False, "error": None}

    try:
        ips = socket.getaddrinfo(domain, None)
        unique_ips = list({addr[4][0] for addr in ips})
        result["resolves"] = True
        result["ip_addresses"] = unique_ips[:5]
    except socket.gaierror as e:
        result["error"] = str(e)

    # Check MX records (has email infrastructure)
    try:
        import subprocess

        mx_result = subprocess.run(
            ["dig", "+short", "MX", domain],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if mx_result.stdout.strip():
            result["has_mx"] = True
    except Exception:
        pass

    return result


def check_historical_dns(domain: str) -> dict:
    """Check Wayback Machine for historical snapshots of the domain.

    Uses the CDX API (same approach as date_checker.py) to find how long
    the domain has been active on the web.

    Returns:
        {
            "found": bool,
            "earliest_snapshot": str or None (YYYY-MM-DD),
            "latest_snapshot": str or None (YYYY-MM-DD),
            "snapshot_count": int,
            "snapshots": list[dict] (date, status),
            "years_of_history": float or None,
            "error": str or None,
        }
    """
    result = {
        "found": False,
        "earliest_snapshot": None,
        "latest_snapshot": None,
        "snapshot_count": 0,
        "snapshots": [],
        "years_of_history": None,
        "error": None,
    }

    try:
        resp = requests.get(
            "https://web.archive.org/cdx/search/cdx",
            params={
                "url": domain,
                "output": "json",
                "fl": "timestamp,statuscode",
                "collapse": "timestamp:6",  # group by year-month
                "limit": 50,
            },
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if resp.status_code != 200:
            result["error"] = f"Wayback CDX returned HTTP {resp.status_code}"
            return result

        data = resp.json()
        if len(data) <= 1:  # first row is header
            return result

        # Skip header row
        rows = data[1:]
        result["found"] = True
        result["snapshot_count"] = len(rows)

        snapshots = []
        for row in rows:
            ts = row[0]  # e.g., "20150301120000"
            status = row[1] if len(row) > 1 else ""
            try:
                snap_date = datetime.strptime(ts[:8], "%Y%m%d").date()
                snapshots.append({
                    "date": snap_date.isoformat(),
                    "status": status or "200",
                })
            except (ValueError, IndexError):
                continue

        result["snapshots"] = snapshots

        if snapshots:
            result["earliest_snapshot"] = snapshots[0]["date"]
            result["latest_snapshot"] = snapshots[-1]["date"]

            earliest = date.fromisoformat(snapshots[0]["date"])
            latest = date.fromisoformat(snapshots[-1]["date"])
            days = (latest - earliest).days
            result["years_of_history"] = round(days / 365.25, 1)

    except Exception as e:
        result["error"] = str(e)

    return result
