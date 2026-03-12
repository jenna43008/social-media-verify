"""Account creation date extraction and comparison utilities."""

import re
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser


WAYBACK_API = "https://archive.org/wayback/available"
WAYBACK_CDX_API = "https://web.archive.org/cdx/search/cdx"


def extract_creation_indicators(url: str, html: str | None, platform: str | None = None) -> dict:
    """Try to determine when a social media account was created.

    Strategies:
      1. Parse visible "Joined" / "Member since" text from the page
      2. Check page metadata for date indicators
      3. Query the Wayback Machine for the earliest snapshot

    Returns a dict with:
      - creation_date: date or None
      - source: str describing how the date was found
      - earliest_snapshot: date or None (from Wayback Machine)
      - confidence: 'high', 'medium', 'low'
    """
    result = {
        "creation_date": None,
        "source": None,
        "earliest_snapshot": None,
        "confidence": "low",
    }

    # Strategy 1: Parse page HTML for date indicators
    if html:
        page_date = _extract_date_from_html(html, platform)
        if page_date:
            result["creation_date"] = page_date
            result["source"] = "Page content (joined/member since text)"
            result["confidence"] = "high"

    # Strategy 2: Check Wayback Machine for earliest snapshot
    wayback_date = _check_wayback_machine(url)
    if wayback_date:
        result["earliest_snapshot"] = wayback_date
        if not result["creation_date"]:
            result["creation_date"] = wayback_date
            result["source"] = "Wayback Machine (earliest archived snapshot)"
            result["confidence"] = "medium"

    return result


def _extract_date_from_html(html: str, platform: str | None) -> date | None:
    """Look for account creation dates in page HTML."""
    soup = BeautifulSoup(html, "lxml")

    # Common patterns for "joined" dates
    join_patterns = [
        r"(?:joined|member since|created|established|founded)\s*:?\s*(\w+ \d{4})",
        r"(?:joined|member since|created|established|founded)\s*:?\s*(\w+ \d{1,2},?\s*\d{4})",
        r"(?:joined|member since|created|established|founded)\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})",
        r"(?:joined|member since|created|established|founded)\s*:?\s*(\d{4}-\d{2}-\d{2})",
    ]

    text = soup.get_text(separator=" ", strip=True)

    for pattern in join_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                parsed = dateutil_parser.parse(match.group(1), fuzzy=True)
                return parsed.date()
            except (ValueError, OverflowError):
                continue

    # Check for Twitter-specific date format in metadata
    if platform == "twitter":
        for el in soup.find_all(attrs={"data-testid": "UserJoinDate"}):
            try:
                parsed = dateutil_parser.parse(el.get_text(), fuzzy=True)
                return parsed.date()
            except (ValueError, OverflowError):
                pass

    # Check structured data / JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        text = script.string or ""
        for pattern in [r'"dateCreated"\s*:\s*"([^"]+)"', r'"foundingDate"\s*:\s*"([^"]+)"']:
            match = re.search(pattern, text)
            if match:
                try:
                    parsed = dateutil_parser.parse(match.group(1))
                    return parsed.date()
                except (ValueError, OverflowError):
                    continue

    return None


def _check_wayback_machine(url: str) -> date | None:
    """Query the Wayback Machine CDX API for the earliest snapshot of a URL."""
    try:
        response = requests.get(
            WAYBACK_CDX_API,
            params={
                "url": url,
                "output": "json",
                "limit": 1,
                "fl": "timestamp",
                "sort": "timestamp:asc",  # oldest first
            },
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            # CDX returns header row + data rows
            if len(data) > 1:
                timestamp = data[1][0]  # format: YYYYMMDDHHmmss
                return datetime.strptime(timestamp[:8], "%Y%m%d").date()
    except Exception:
        pass

    # Fallback to availability API
    try:
        response = requests.get(
            WAYBACK_API,
            params={"url": url, "timestamp": "19900101"},
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            snapshot = data.get("archived_snapshots", {}).get("closest", {})
            if snapshot.get("timestamp"):
                ts = snapshot["timestamp"]
                return datetime.strptime(ts[:8], "%Y%m%d").date()
    except Exception:
        pass

    return None


def check_predates_denial(creation_date: date | None, denial_date: date) -> dict:
    """Compare account creation date against the denial date.

    Returns a dict with:
      - predates: bool or None (if creation_date is unknown)
      - days_before: int or None
      - message: str
    """
    if creation_date is None:
        return {
            "predates": None,
            "days_before": None,
            "message": "Could not determine account creation date. Manual review required.",
        }

    days_diff = (denial_date - creation_date).days

    if days_diff > 0:
        return {
            "predates": True,
            "days_before": days_diff,
            "message": f"Account appears to predate the denial by {days_diff} days ({creation_date.isoformat()}).",
        }
    elif days_diff == 0:
        return {
            "predates": None,
            "days_before": 0,
            "message": f"Account creation date matches the denial date ({creation_date.isoformat()}). Manual review recommended.",
        }
    else:
        return {
            "predates": False,
            "days_before": days_diff,
            "message": f"Account was created {abs(days_diff)} days AFTER the denial ({creation_date.isoformat()}).",
        }
