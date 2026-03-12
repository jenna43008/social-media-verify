"""Profile page scraping and domain reference detection."""

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup


def scrape_profile(html: str, platform: str | None = None) -> dict:
    """Extract structured data from a social media profile page.

    Returns a dict with:
      - title: page title
      - description: meta description
      - bio_text: combined text from bio/about sections
      - links_found: list of URLs found on the page
      - raw_text: full visible text (for fallback searching)
      - og_data: Open Graph metadata
    """
    soup = BeautifulSoup(html, "lxml")

    # Open Graph metadata (works even when page content is JS-rendered)
    og_data = {}
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        content = meta.get("content", "")
        if prop.startswith("og:") and content:
            og_data[prop] = content

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    description = ""
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        description = meta_desc["content"]

    # Extract bio / about text based on platform
    bio_text = _extract_bio(soup, platform)

    # Collect all links on the page
    links_found = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if href.startswith(("http://", "https://")):
            links_found.append(href)

    # Full visible text for fallback
    raw_text = soup.get_text(separator=" ", strip=True)

    return {
        "title": title,
        "description": description,
        "bio_text": bio_text,
        "links_found": links_found,
        "raw_text": raw_text,
        "og_data": og_data,
    }


def _extract_bio(soup: BeautifulSoup, platform: str | None) -> str:
    """Extract bio/about text using platform-specific selectors with fallbacks."""
    bio_parts = []

    if platform == "linkedin":
        # LinkedIn public pages use specific sections
        for selector in [
            "section.about",
            ".core-section-container",
            '[data-section="summary"]',
            ".description",
            ".top-card-layout__headline",
            ".top-card-layout__summary",
        ]:
            elements = soup.select(selector)
            for el in elements:
                text = el.get_text(separator=" ", strip=True)
                if text:
                    bio_parts.append(text)

    elif platform == "facebook":
        for selector in [
            '[data-testid="page_about"]',
            ".pageAboutHeader",
            "#pages_msite_body_contents",
            'div[role="main"]',
        ]:
            elements = soup.select(selector)
            for el in elements:
                text = el.get_text(separator=" ", strip=True)
                if text:
                    bio_parts.append(text)

    elif platform == "twitter":
        for selector in [
            '[data-testid="UserDescription"]',
            ".ProfileHeaderCard-bio",
            '[data-testid="UserProfileHeader_Items"]',
        ]:
            elements = soup.select(selector)
            for el in elements:
                text = el.get_text(separator=" ", strip=True)
                if text:
                    bio_parts.append(text)

    elif platform == "instagram":
        for selector in [
            ".-vDIg span",
            "header section div span",
        ]:
            elements = soup.select(selector)
            for el in elements:
                text = el.get_text(separator=" ", strip=True)
                if text:
                    bio_parts.append(text)

    # Fallback: look for common about/bio patterns
    if not bio_parts:
        for selector in [
            '[class*="about"]',
            '[class*="bio"]',
            '[class*="description"]',
            '[class*="summary"]',
            '[id*="about"]',
            '[id*="bio"]',
        ]:
            elements = soup.select(selector)
            for el in elements:
                text = el.get_text(separator=" ", strip=True)
                if text and len(text) > 10:
                    bio_parts.append(text)

    return " ".join(bio_parts)


def check_domain_in_profile(profile_data: dict, domain: str) -> dict:
    """Check whether a domain is referenced in the scraped profile data.

    Returns a dict with:
      - found: bool
      - locations: list of where the domain was found
      - confidence: 'high', 'medium', 'low'
    """
    if not domain:
        return {"found": False, "locations": [], "confidence": "low"}

    # Normalize domain — strip protocol, www, trailing slash
    domain = domain.lower().strip()
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    domain = domain.rstrip("/")

    locations = []

    # Check OG metadata
    for key, value in profile_data.get("og_data", {}).items():
        if domain in value.lower():
            locations.append(f"Open Graph ({key})")

    # Check meta description
    if domain in profile_data.get("description", "").lower():
        locations.append("Meta description")

    # Check bio text
    if domain in profile_data.get("bio_text", "").lower():
        locations.append("Bio / About section")

    # Check links
    for link in profile_data.get("links_found", []):
        link_domain = urlparse(link).hostname or ""
        link_domain = re.sub(r"^www\.", "", link_domain.lower())
        if domain in link_domain:
            locations.append(f"Link: {link}")

    # Fallback: check raw page text
    if not locations and domain in profile_data.get("raw_text", "").lower():
        locations.append("Page text (general)")

    # Determine confidence
    if not locations:
        confidence = "low"
    elif any("Bio" in loc or "Link:" in loc for loc in locations):
        confidence = "high"
    elif any("Open Graph" in loc or "Meta" in loc for loc in locations):
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "found": bool(locations),
        "locations": locations,
        "confidence": confidence,
    }
