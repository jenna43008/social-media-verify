"""Developer and startup signal detection.

Checks GitHub, npm, Product Hunt, Crunchbase, app stores,
tech blog, Stack Overflow presence to identify legitimate
startups/developers that may not have large social followings.
"""

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


def _check_url(url: str) -> tuple[bool, str | None]:
    """Check if URL exists, return (exists, html)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code < 400:
            return True, resp.text
        return False, None
    except Exception:
        return False, None


def _search_duckduckgo(query: str, max_results: int = 5) -> list[str]:
    """Search DuckDuckGo and return URLs."""
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


def check_github_presence(domain: str, company_name: str = "") -> dict:
    """Check for GitHub organization or user matching the company.

    Uses the GitHub API (no auth required for basic checks).
    """
    result = {
        "found": False,
        "url": None,
        "org_name": None,
        "public_repos": None,
        "followers": None,
        "created_at": None,
        "description": None,
        "is_active": False,
    }

    slug = domain.split(".")[0].lower()
    slugs = [slug]
    if company_name:
        alt = company_name.lower().replace(" ", "").replace("-", "")
        if alt != slug:
            slugs.append(alt)
        alt2 = company_name.lower().replace(" ", "-")
        if alt2 != slug:
            slugs.append(alt2)

    for s in slugs:
        # Try as org first
        try:
            resp = requests.get(
                f"https://api.github.com/orgs/{s}",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                result["found"] = True
                result["url"] = data.get("html_url")
                result["org_name"] = data.get("login")
                result["public_repos"] = data.get("public_repos", 0)
                result["followers"] = data.get("followers", 0)
                result["created_at"] = data.get("created_at")
                result["description"] = data.get("description")
                result["is_active"] = (data.get("public_repos", 0) > 0)
                return result
        except Exception:
            pass

        # Try as user
        try:
            resp = requests.get(
                f"https://api.github.com/users/{s}",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                result["found"] = True
                result["url"] = data.get("html_url")
                result["org_name"] = data.get("login")
                result["public_repos"] = data.get("public_repos", 0)
                result["followers"] = data.get("followers", 0)
                result["created_at"] = data.get("created_at")
                result["description"] = data.get("bio")
                result["is_active"] = (data.get("public_repos", 0) > 0)
                return result
        except Exception:
            pass

        time.sleep(0.2)

    return result


def check_npm_presence(domain: str, company_name: str = "") -> dict:
    """Check for npm packages published by the company."""
    result = {"found": False, "packages": [], "url": None}

    slug = domain.split(".")[0].lower()
    queries = [slug]
    if company_name:
        queries.append(company_name.lower().replace(" ", "-"))

    for q in queries:
        try:
            # npm org scope
            resp = requests.get(
                f"https://registry.npmjs.org/-/v1/search?text=scope:{q}&size=5",
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                objects = data.get("objects", [])
                if objects:
                    result["found"] = True
                    result["url"] = f"https://www.npmjs.com/org/{q}"
                    result["packages"] = [
                        {
                            "name": obj["package"]["name"],
                            "description": obj["package"].get("description", ""),
                            "version": obj["package"].get("version", ""),
                        }
                        for obj in objects[:5]
                    ]
                    return result

            # Search by keyword
            resp = requests.get(
                f"https://registry.npmjs.org/-/v1/search?text={q}&size=5",
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                objects = data.get("objects", [])
                # Filter to likely matches
                for obj in objects:
                    pkg = obj["package"]
                    name = pkg.get("name", "").lower()
                    publisher = pkg.get("publisher", {}).get("username", "").lower()
                    if q in name or q in publisher:
                        if not result["found"]:
                            result["found"] = True
                            result["url"] = f"https://www.npmjs.com/search?q={q}"
                        result["packages"].append({
                            "name": pkg["name"],
                            "description": pkg.get("description", ""),
                            "version": pkg.get("version", ""),
                        })
        except Exception:
            pass

        time.sleep(0.2)

    return result


def check_product_hunt(domain: str, company_name: str = "") -> dict:
    """Check for Product Hunt presence."""
    result = {"found": False, "url": None, "product_name": None, "tagline": None}

    company = company_name or domain.split(".")[0]
    search_urls = _search_duckduckgo(f'"{company}" site:producthunt.com', max_results=3)

    for url in search_urls:
        if "producthunt.com" in url.lower():
            exists, html = _check_url(url)
            if exists and html:
                soup = BeautifulSoup(html, "lxml")
                result["found"] = True
                result["url"] = url
                og_title = soup.find("meta", property="og:title")
                if og_title:
                    result["product_name"] = og_title.get("content", "")
                og_desc = soup.find("meta", property="og:description")
                if og_desc:
                    result["tagline"] = og_desc.get("content", "")[:150]
                break

    return result


def check_crunchbase(domain: str, company_name: str = "") -> dict:
    """Check for Crunchbase presence (indicates funded startup)."""
    result = {"found": False, "url": None, "summary": None}

    company = company_name or domain.split(".")[0]
    search_urls = _search_duckduckgo(f'"{company}" site:crunchbase.com/organization', max_results=3)

    for url in search_urls:
        if "crunchbase.com" in url.lower():
            result["found"] = True
            result["url"] = url

            exists, html = _check_url(url)
            if exists and html:
                soup = BeautifulSoup(html, "lxml")
                og_desc = soup.find("meta", property="og:description")
                if og_desc:
                    result["summary"] = og_desc.get("content", "")[:200]
            break

    return result


def check_app_stores(domain: str, company_name: str = "") -> dict:
    """Check for presence on Apple App Store and Google Play Store."""
    result = {
        "apple": {"found": False, "url": None, "app_name": None},
        "google": {"found": False, "url": None, "app_name": None},
    }

    company = company_name or domain.split(".")[0]

    # Apple App Store
    urls = _search_duckduckgo(f'"{company}" site:apps.apple.com', max_results=3)
    for url in urls:
        if "apps.apple.com" in url.lower():
            result["apple"]["found"] = True
            result["apple"]["url"] = url
            exists, html = _check_url(url)
            if exists and html:
                soup = BeautifulSoup(html, "lxml")
                og_title = soup.find("meta", property="og:title")
                if og_title:
                    result["apple"]["app_name"] = og_title.get("content", "")
            break

    time.sleep(0.3)

    # Google Play Store
    urls = _search_duckduckgo(f'"{company}" site:play.google.com', max_results=3)
    for url in urls:
        if "play.google.com" in url.lower():
            result["google"]["found"] = True
            result["google"]["url"] = url
            exists, html = _check_url(url)
            if exists and html:
                soup = BeautifulSoup(html, "lxml")
                og_title = soup.find("meta", property="og:title")
                if og_title:
                    result["google"]["app_name"] = og_title.get("content", "")
            break

    return result


def check_stack_overflow(domain: str, company_name: str = "") -> dict:
    """Check for Stack Overflow presence (tags, company page)."""
    result = {"found": False, "url": None, "type": None}

    company = company_name or domain.split(".")[0]
    urls = _search_duckduckgo(f'"{company}" site:stackoverflow.com', max_results=3)

    for url in urls:
        if "stackoverflow.com" in url.lower():
            result["found"] = True
            result["url"] = url
            if "/questions/tagged/" in url:
                result["type"] = "tag"
            elif "/company/" in url or "/jobs/companies/" in url:
                result["type"] = "company_page"
            else:
                result["type"] = "mention"
            break

    return result


def check_tech_blog(domain: str) -> dict:
    """Check if the company has a tech blog or documentation site."""
    result = {"found": False, "url": None, "type": None}

    blog_paths = [
        f"https://{domain}/blog",
        f"https://blog.{domain}",
        f"https://{domain}/docs",
        f"https://docs.{domain}",
        f"https://{domain}/engineering",
        f"https://{domain}/developers",
        f"https://developer.{domain}",
    ]

    for url in blog_paths:
        exists, html = _check_url(url)
        if exists:
            result["found"] = True
            result["url"] = url
            if "/blog" in url or "blog." in url:
                result["type"] = "blog"
            elif "/docs" in url or "docs." in url:
                result["type"] = "documentation"
            elif "/developer" in url or "developer." in url:
                result["type"] = "developer_portal"
            elif "/engineering" in url:
                result["type"] = "engineering_blog"
            else:
                result["type"] = "other"
            break
        time.sleep(0.2)

    return result


def gather_all_tech_signals(domain: str, company_name: str = "", progress_callback=None) -> dict:
    """Run all tech signal checks and return consolidated results."""

    def _cb(msg):
        if progress_callback:
            progress_callback(msg)

    _cb("Checking GitHub presence...")
    github = check_github_presence(domain, company_name)

    _cb("Checking npm packages...")
    npm = check_npm_presence(domain, company_name)

    _cb("Checking Product Hunt...")
    product_hunt = check_product_hunt(domain, company_name)

    _cb("Checking Crunchbase...")
    crunchbase = check_crunchbase(domain, company_name)

    _cb("Checking app stores...")
    app_stores = check_app_stores(domain, company_name)

    _cb("Checking Stack Overflow...")
    stack_overflow = check_stack_overflow(domain, company_name)

    _cb("Checking for tech blog/docs...")
    tech_blog = check_tech_blog(domain)

    return {
        "github": github,
        "npm": npm,
        "product_hunt": product_hunt,
        "crunchbase": crunchbase,
        "app_stores": app_stores,
        "stack_overflow": stack_overflow,
        "tech_blog": tech_blog,
    }


def calculate_tech_score(signals: dict) -> dict:
    """Calculate a tech/startup legitimacy score.

    Returns:
        {
            "score": float (0-100),
            "is_likely_tech_company": bool,
            "signals_found": int,
            "flags": list[str],
        }
    """
    score = 0.0
    signals_found = 0
    flags = []

    # GitHub (strong signal)
    gh = signals.get("github", {})
    if gh.get("found"):
        signals_found += 1
        repos = gh.get("public_repos", 0)
        if repos >= 20:
            score += 25
            flags.append(f"Active GitHub presence ({repos} repos)")
        elif repos >= 5:
            score += 18
            flags.append(f"GitHub presence ({repos} repos)")
        elif repos >= 1:
            score += 10
            flags.append(f"GitHub account ({repos} repo(s))")
        else:
            score += 5
            flags.append("GitHub account (no public repos)")

    # npm
    if signals.get("npm", {}).get("found"):
        signals_found += 1
        pkg_count = len(signals["npm"].get("packages", []))
        score += min(15, 5 + pkg_count * 3)
        flags.append(f"npm packages found ({pkg_count})")

    # Product Hunt
    if signals.get("product_hunt", {}).get("found"):
        signals_found += 1
        score += 12
        flags.append("Listed on Product Hunt")

    # Crunchbase (strong signal for startups)
    if signals.get("crunchbase", {}).get("found"):
        signals_found += 1
        score += 15
        flags.append("Crunchbase profile found (likely funded startup)")

    # App stores
    app_stores = signals.get("app_stores", {})
    if app_stores.get("apple", {}).get("found"):
        signals_found += 1
        score += 10
        flags.append("Apple App Store listing")
    if app_stores.get("google", {}).get("found"):
        signals_found += 1
        score += 10
        flags.append("Google Play Store listing")

    # Stack Overflow
    if signals.get("stack_overflow", {}).get("found"):
        signals_found += 1
        so_type = signals["stack_overflow"].get("type", "mention")
        if so_type == "tag":
            score += 12
            flags.append("Stack Overflow tag exists")
        elif so_type == "company_page":
            score += 8
            flags.append("Stack Overflow company page")
        else:
            score += 5
            flags.append("Stack Overflow mentions")

    # Tech blog
    if signals.get("tech_blog", {}).get("found"):
        signals_found += 1
        score += 10
        blog_type = signals["tech_blog"].get("type", "blog")
        flags.append(f"Has {blog_type.replace('_', ' ')}")

    is_likely_tech = signals_found >= 2 and (
        gh.get("found") or signals.get("npm", {}).get("found")
    )

    if signals_found == 0:
        flags.append("No tech/developer signals found")

    return {
        "score": min(score, 100),
        "is_likely_tech_company": is_likely_tech,
        "signals_found": signals_found,
        "flags": flags,
    }
