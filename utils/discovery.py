"""Social media profile discovery via search engines and URL pattern matching."""

import re
import time
from urllib.parse import quote_plus, urlparse, urljoin

import requests
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

# Social media platforms and their URL patterns
PLATFORMS = {
    "linkedin": {
        "label": "LinkedIn",
        "search_query": '"{domain}" site:linkedin.com/company',
        "direct_patterns": [
            "https://www.linkedin.com/company/{slug}",
            "https://linkedin.com/company/{slug}",
        ],
    },
    "facebook": {
        "label": "Facebook",
        "search_query": '"{domain}" site:facebook.com',
        "direct_patterns": [
            "https://www.facebook.com/{slug}",
            "https://facebook.com/{slug}",
        ],
    },
    "twitter": {
        "label": "Twitter / X",
        "search_query": '"{domain}" site:twitter.com OR site:x.com',
        "direct_patterns": [
            "https://twitter.com/{slug}",
            "https://x.com/{slug}",
        ],
    },
    "instagram": {
        "label": "Instagram",
        "search_query": '"{domain}" site:instagram.com',
        "direct_patterns": [
            "https://www.instagram.com/{slug}",
            "https://instagram.com/{slug}",
        ],
    },
}


def _search_duckduckgo(query: str, max_results: int = 10) -> list[str]:
    """Search DuckDuckGo HTML and return a list of result URLs."""
    urls = []
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            for link in soup.select("a.result__a"):
                href = link.get("href", "")
                if href and href.startswith(("http://", "https://")):
                    urls.append(href)
                if len(urls) >= max_results:
                    break
    except Exception:
        pass
    return urls


def _search_google(query: str, max_results: int = 10) -> list[str]:
    """Search Google and return a list of result URLs."""
    urls = []
    try:
        resp = requests.get(
            "https://www.google.com/search",
            params={"q": query, "num": max_results},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                # Google wraps results in /url?q=...
                if href.startswith("/url?q="):
                    actual_url = href.split("/url?q=")[1].split("&")[0]
                    if actual_url.startswith(("http://", "https://")):
                        urls.append(actual_url)
                        if len(urls) >= max_results:
                            break
    except Exception:
        pass
    return urls


def _check_url_exists(url: str) -> bool:
    """Quick check if a URL returns a 2xx response."""
    try:
        resp = requests.head(url, headers=HEADERS, timeout=10, allow_redirects=True)
        return resp.status_code < 400
    except Exception:
        return False


def _extract_domain_slug(domain: str) -> list[str]:
    """Generate possible social media slugs from a domain.

    e.g., 'acme-corp.com' -> ['acme-corp', 'acmecorp', 'acme_corp']
    """
    # Strip TLD
    base = domain.split(".")[0].lower()
    slugs = [base]

    # Variations
    if "-" in base:
        slugs.append(base.replace("-", ""))
        slugs.append(base.replace("-", "_"))
    if "_" in base:
        slugs.append(base.replace("_", ""))
        slugs.append(base.replace("_", "-"))

    return list(dict.fromkeys(slugs))  # dedupe preserving order


def discover_social_profiles(
    domain: str,
    website_social_links: dict | None = None,
    progress_callback=None,
) -> dict:
    """Discover social media profiles for a given domain.

    Priority order:
      1. Links found on the company's own website (most reliable)
      2. Search engine results
      3. Direct URL pattern matching

    Args:
        domain: The company's domain (e.g., "acme.com")
        website_social_links: Dict of platform->url scraped from the company's
            own website by domain_intel.scrape_website_social_links().
        progress_callback: Optional function to report progress.

    Returns a dict keyed by platform:
        {
            "linkedin": {"url": "...", "source": "website" | "search" | "pattern", ...},
            ...
        }
    """
    domain = domain.lower().strip()
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    domain = domain.rstrip("/")

    website_social_links = website_social_links or {}
    slugs = _extract_domain_slug(domain)
    results = {}

    for platform_key, platform_info in PLATFORMS.items():
        if progress_callback:
            progress_callback(f"Searching for {platform_info['label']} profiles...")

        found_url = None
        source = None

        # Strategy 1: Use link from company's own website (most reliable)
        if platform_key in website_social_links:
            candidate = website_social_links[platform_key]
            if _check_url_exists(candidate):
                found_url = candidate
                source = "company website"

        # Strategy 2: Search engines
        if not found_url:
            query = platform_info["search_query"].format(domain=domain)

            # Try Google first, then DuckDuckGo
            search_urls = _search_google(query)
            if not search_urls:
                time.sleep(0.5)
                search_urls = _search_duckduckgo(query)

            platform_domains = _get_platform_domains(platform_key)
            for url in search_urls:
                parsed = urlparse(url)
                hostname = (parsed.hostname or "").lower()
                if any(pd in hostname for pd in platform_domains):
                    if platform_key == "linkedin" and "/company/" not in url:
                        continue
                    found_url = url
                    source = "search"
                    break

        # Strategy 3: Direct URL pattern matching (fallback)
        if not found_url:
            for slug in slugs:
                for pattern in platform_info["direct_patterns"]:
                    test_url = pattern.format(slug=slug)
                    if _check_url_exists(test_url):
                        found_url = test_url
                        source = "pattern"
                        break
                if found_url:
                    break

        if found_url:
            results[platform_key] = {
                "url": found_url,
                "label": platform_info["label"],
                "source": source,
                "verified": False,
            }

        time.sleep(0.3)

    return results


def _get_platform_domains(platform_key: str) -> list[str]:
    """Return domain substrings that identify a platform."""
    mapping = {
        "linkedin": ["linkedin.com"],
        "facebook": ["facebook.com", "fb.com"],
        "twitter": ["twitter.com", "x.com"],
        "instagram": ["instagram.com"],
    }
    return mapping.get(platform_key, [])


def discover_employees(domain: str, company_name: str = "", progress_callback=None) -> list[dict]:
    """Search for employee profiles linked to the company.

    Returns a list of dicts:
        [{"name": "...", "title": "...", "url": "...", "platform": "linkedin"}, ...]
    """
    domain = domain.lower().strip()
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    domain = domain.rstrip("/")

    company_base = company_name or domain.split(".")[0]
    employees = []

    if progress_callback:
        progress_callback("Searching for employee profiles...")

    # Search for LinkedIn profiles mentioning the company
    queries = [
        f'"{company_base}" site:linkedin.com/in/',
    ]
    if company_name and company_name.lower() != domain.split(".")[0].lower():
        queries.append(f'"{company_name}" site:linkedin.com/in/')

    seen_urls = set()

    for query in queries:
        search_urls = _search_google(query, max_results=20)
        if not search_urls:
            time.sleep(0.5)
            search_urls = _search_duckduckgo(query, max_results=20)

        for url in search_urls:
            parsed = urlparse(url)
            hostname = (parsed.hostname or "").lower()

            if "linkedin.com" not in hostname:
                continue
            if "/in/" not in url:
                continue

            # Normalize URL
            clean_url = url.split("?")[0].rstrip("/")
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            # Try to extract name from URL
            name = _name_from_linkedin_url(clean_url)

            # Try to get title from page
            title = _get_employee_title(clean_url, company_base)

            employees.append({
                "name": name,
                "title": title,
                "url": clean_url,
                "platform": "linkedin",
            })

        time.sleep(0.3)

    return employees


def _name_from_linkedin_url(url: str) -> str:
    """Extract a display name from a LinkedIn profile URL."""
    path = urlparse(url).path
    slug = path.rstrip("/").split("/")[-1]
    # LinkedIn slugs are like "john-doe-12345" or "johndoe"
    # Remove trailing numbers
    slug = re.sub(r"-[\da-f]{6,}$", "", slug)
    slug = re.sub(r"-\d+$", "", slug)
    return slug.replace("-", " ").title()


def _get_employee_title(url: str, company_hint: str) -> str:
    """Try to fetch the employee's title from their LinkedIn page meta tags."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            # LinkedIn public profiles have title in <title> or og:title
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                # Format: "Name - Title - Company | LinkedIn"
                parts = og_title["content"].split(" - ")
                if len(parts) >= 2:
                    return parts[1].strip()

            desc = soup.find("meta", attrs={"name": "description"})
            if desc and desc.get("content"):
                content = desc["content"]
                # Often: "Name · Title at Company · ..."
                if "·" in content:
                    parts = content.split("·")
                    if len(parts) >= 2:
                        return parts[1].strip()
    except Exception:
        pass
    return ""
