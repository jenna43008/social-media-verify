"""Review discovery across multiple platforms."""

import re
import time

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

TIMEOUT = 12

# Review platforms to check
REVIEW_PLATFORMS = {
    "google_business": {
        "label": "Google Business",
        "search_query": '"{domain}" site:google.com/maps OR site:business.google.com',
        "icon": "🔍",
    },
    "bbb": {
        "label": "Better Business Bureau",
        "search_query": '"{company}" site:bbb.org',
        "icon": "🏢",
    },
    "trustpilot": {
        "label": "Trustpilot",
        "search_query": '"{domain}" site:trustpilot.com',
        "direct_url": "https://www.trustpilot.com/review/{domain}",
        "icon": "⭐",
    },
    "glassdoor": {
        "label": "Glassdoor",
        "search_query": '"{company}" site:glassdoor.com',
        "icon": "🪟",
    },
    "g2": {
        "label": "G2",
        "search_query": '"{company}" site:g2.com',
        "icon": "📊",
    },
    "yelp": {
        "label": "Yelp",
        "search_query": '"{company}" site:yelp.com',
        "icon": "📍",
    },
    "capterra": {
        "label": "Capterra",
        "search_query": '"{company}" site:capterra.com',
        "icon": "💻",
    },
}


def _search_duckduckgo(query: str, max_results: int = 5) -> list[str]:
    """Search DuckDuckGo and return result URLs."""
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
                if href.startswith(("http://", "https://")):
                    urls.append(href)
                if len(urls) >= max_results:
                    break
    except Exception:
        pass
    return urls


def _check_url(url: str) -> tuple[bool, str | None]:
    """Check if a URL exists and return (exists, html)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code < 400:
            return True, resp.text
        return False, None
    except Exception:
        return False, None


def _extract_trustpilot_data(html: str) -> dict:
    """Extract rating data from a Trustpilot page."""
    data = {"rating": None, "review_count": None, "summary": None}
    soup = BeautifulSoup(html, "lxml")

    # Try to find TrustScore
    score_el = soup.find(attrs={"data-rating-typography": True})
    if score_el:
        data["rating"] = score_el.get_text(strip=True)

    # Review count from meta or text
    for el in soup.find_all(string=re.compile(r"\d+\s+reviews?")):
        match = re.search(r"([\d,]+)\s+reviews?", el)
        if match:
            data["review_count"] = match.group(1)
            break

    # OG description often has summary
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        data["summary"] = og_desc["content"][:200]

    # Try JSON-LD
    import json
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "")
            if isinstance(ld, dict):
                agg = ld.get("aggregateRating")
                if agg:
                    data["rating"] = data["rating"] or str(agg.get("ratingValue", ""))
                    data["review_count"] = data["review_count"] or str(agg.get("reviewCount", ""))
        except Exception:
            pass

    return data


def _extract_bbb_data(html: str) -> dict:
    """Extract rating data from a BBB page."""
    data = {"rating": None, "accredited": None, "summary": None}
    soup = BeautifulSoup(html, "lxml")

    text = soup.get_text(separator=" ", strip=True)

    # BBB letter grades
    grade_match = re.search(r"BBB Rating:\s*([A-F][+-]?)", text)
    if grade_match:
        data["rating"] = grade_match.group(1)

    # Accreditation
    if "BBB Accredited" in text or "Accredited Business" in text:
        data["accredited"] = True
    elif "not BBB Accredited" in text.lower() or "not accredited" in text.lower():
        data["accredited"] = False

    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        data["summary"] = og_desc["content"][:200]

    return data


def _extract_generic_review_data(html: str) -> dict:
    """Extract review data from generic review pages using common patterns."""
    data = {"rating": None, "review_count": None, "summary": None}
    soup = BeautifulSoup(html, "lxml")

    # Try JSON-LD for aggregate ratings
    import json
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "")
            items = ld if isinstance(ld, list) else [ld]
            for item in items:
                agg = item.get("aggregateRating")
                if agg:
                    data["rating"] = str(agg.get("ratingValue", ""))
                    data["review_count"] = str(agg.get("reviewCount", ""))
                    break
        except Exception:
            pass

    # OG description
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        data["summary"] = og_desc["content"][:200]

    return data


def discover_reviews(domain: str, company_name: str = "", progress_callback=None) -> dict:
    """Search for company reviews across all platforms.

    Returns:
        {
            "trustpilot": {"found": bool, "url": str, "rating": ..., ...},
            "bbb": {"found": bool, ...},
            ...
        }
    """
    company = company_name or domain.split(".")[0].replace("-", " ").replace("_", " ").title()
    results = {}

    for key, platform in REVIEW_PLATFORMS.items():
        if progress_callback:
            progress_callback(f"Checking {platform['label']}...")

        entry = {
            "found": False,
            "label": platform["label"],
            "icon": platform["icon"],
            "url": None,
            "rating": None,
            "review_count": None,
            "summary": None,
            "extra": {},
        }

        # Strategy 1: Direct URL (e.g., Trustpilot)
        if "direct_url" in platform:
            direct = platform["direct_url"].format(domain=domain)
            exists, html = _check_url(direct)
            if exists and html:
                entry["found"] = True
                entry["url"] = direct

                if key == "trustpilot":
                    tp_data = _extract_trustpilot_data(html)
                    entry.update({k: v for k, v in tp_data.items() if v is not None})

        # Strategy 2: Search engine
        if not entry["found"]:
            query = platform["search_query"].format(domain=domain, company=company)
            search_results = _search_duckduckgo(query, max_results=3)

            for url in search_results:
                # Verify the URL is from the right platform
                platform_domain = _get_platform_domain(key)
                if platform_domain and platform_domain not in url.lower():
                    continue

                exists, html = _check_url(url)
                if exists and html:
                    entry["found"] = True
                    entry["url"] = url

                    if key == "trustpilot":
                        data = _extract_trustpilot_data(html)
                    elif key == "bbb":
                        data = _extract_bbb_data(html)
                    else:
                        data = _extract_generic_review_data(html)

                    entry.update({k: v for k, v in data.items() if v is not None})
                    break

        results[key] = entry
        time.sleep(0.3)

    return results


def _get_platform_domain(key: str) -> str | None:
    """Map platform key to expected domain in URLs."""
    mapping = {
        "google_business": "google.com",
        "bbb": "bbb.org",
        "trustpilot": "trustpilot.com",
        "glassdoor": "glassdoor.com",
        "g2": "g2.com",
        "yelp": "yelp.com",
        "capterra": "capterra.com",
    }
    return mapping.get(key)


def calculate_review_score(reviews: dict) -> dict:
    """Calculate a review-based legitimacy score.

    Returns:
        {
            "score": float (0-100),
            "platforms_found": int,
            "platforms_with_ratings": int,
            "flags": list[str],
        }
    """
    platforms_found = sum(1 for r in reviews.values() if r["found"])
    platforms_with_ratings = sum(
        1 for r in reviews.values() if r["found"] and r.get("rating")
    )

    flags = []
    score = 0.0

    # Base score: having reviews at all
    if platforms_found == 0:
        score = 10
        flags.append("No review presence found on any platform")
    elif platforms_found == 1:
        score = 30
        flags.append("Limited review presence (1 platform)")
    elif platforms_found == 2:
        score = 50
    elif platforms_found >= 3:
        score = 70

    # Bonus for ratings
    if platforms_with_ratings >= 2:
        score += 15
    elif platforms_with_ratings == 1:
        score += 8

    # BBB accreditation bonus
    bbb = reviews.get("bbb", {})
    if bbb.get("found") and bbb.get("extra", {}).get("accredited"):
        score += 15
        flags.append("BBB Accredited")
    elif bbb.get("found") and bbb.get("rating"):
        grade = bbb["rating"].upper()
        if grade.startswith("A"):
            score += 10
        elif grade.startswith("B"):
            score += 5
        elif grade.startswith(("D", "F")):
            score -= 10
            flags.append(f"Low BBB rating: {grade}")

    return {
        "score": min(max(score, 0), 100),
        "platforms_found": platforms_found,
        "platforms_with_ratings": platforms_with_ratings,
        "flags": flags,
    }
