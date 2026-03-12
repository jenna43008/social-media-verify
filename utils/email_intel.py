"""Email intelligence: validation, person lookup, name extraction from email address."""

import hashlib
import re
import time
from urllib.parse import quote_plus, urlparse

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


# ---------------------------------------------------------------------------
# Email validation & domain extraction
# ---------------------------------------------------------------------------

def validate_email(email: str) -> dict:
    """Validate email format and extract domain.

    Returns:
        {
            "valid": bool,
            "email": str (normalized),
            "local_part": str,
            "domain": str,
            "error": str or None,
        }
    """
    email = email.strip().lower()
    result = {"valid": False, "email": email, "local_part": "", "domain": "", "error": None}

    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email):
        result["error"] = "Invalid email format."
        return result

    local_part, domain = email.rsplit("@", 1)
    result["valid"] = True
    result["local_part"] = local_part
    result["domain"] = domain
    return result


# ---------------------------------------------------------------------------
# Name extraction from email prefix
# ---------------------------------------------------------------------------

def extract_name_from_email(local_part: str) -> dict:
    """Parse email prefix patterns to guess first/last name.

    Returns:
        {
            "candidates": [{"first": str, "last": str, "confidence": str, "pattern": str}, ...],
            "raw_prefix": str,
        }
    """
    local_part = local_part.strip().lower()
    candidates = []

    # Pattern 1: first.last
    if "." in local_part:
        parts = local_part.split(".")
        if len(parts) == 2 and len(parts[0]) >= 2 and len(parts[1]) >= 2:
            candidates.append({
                "first": parts[0].title(),
                "last": parts[1].title(),
                "confidence": "high",
                "pattern": "first.last",
            })
        elif len(parts) == 2 and len(parts[0]) == 1 and len(parts[1]) >= 2:
            candidates.append({
                "first": parts[0].upper(),
                "last": parts[1].title(),
                "confidence": "medium",
                "pattern": "initial.last",
            })

    # Pattern 2: first_last
    if "_" in local_part:
        parts = local_part.split("_")
        if len(parts) == 2 and len(parts[0]) >= 2 and len(parts[1]) >= 2:
            candidates.append({
                "first": parts[0].title(),
                "last": parts[1].title(),
                "confidence": "high",
                "pattern": "first_last",
            })

    # Pattern 3: first-last
    if "-" in local_part:
        parts = local_part.split("-")
        if len(parts) == 2 and len(parts[0]) >= 2 and len(parts[1]) >= 2:
            candidates.append({
                "first": parts[0].title(),
                "last": parts[1].title(),
                "confidence": "high",
                "pattern": "first-last",
            })

    # Pattern 4: single word — try initial + rest as last name
    if not candidates and local_part.isalpha() and len(local_part) >= 3:
        # First letter + rest (e.g., "glairet" → G + Lairet)
        candidates.append({
            "first": local_part[0].upper(),
            "last": local_part[1:].title(),
            "confidence": "low",
            "pattern": "initial_rest",
        })
        # Also keep the full prefix as a search term
        candidates.append({
            "first": local_part.title(),
            "last": "",
            "confidence": "low",
            "pattern": "single_word",
        })

    return {"candidates": candidates, "raw_prefix": local_part}


# ---------------------------------------------------------------------------
# Gravatar lookup
# ---------------------------------------------------------------------------

def check_gravatar(email: str) -> dict:
    """Check Gravatar for a profile associated with the email.

    Returns:
        {
            "found": bool,
            "profile_url": str or None,
            "display_name": str or None,
            "photos": list[str],
            "accounts": list[dict],
            "error": str or None,
        }
    """
    result = {
        "found": False,
        "profile_url": None,
        "display_name": None,
        "photos": [],
        "accounts": [],
        "error": None,
    }

    email_hash = hashlib.md5(email.strip().lower().encode()).hexdigest()
    url = f"https://en.gravatar.com/{email_hash}.json"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 404:
            return result
        if resp.status_code != 200:
            result["error"] = f"Gravatar returned HTTP {resp.status_code}"
            return result

        data = resp.json()
        entry = data.get("entry", [{}])[0]

        result["found"] = True
        result["profile_url"] = entry.get("profileUrl")

        # Display name
        name_data = entry.get("name", {})
        if name_data.get("formatted"):
            result["display_name"] = name_data["formatted"]
        elif entry.get("displayName"):
            result["display_name"] = entry["displayName"]

        # Photos
        for photo in entry.get("photos", []):
            if photo.get("value"):
                result["photos"].append(photo["value"])

        # Linked accounts
        for acct in entry.get("accounts", []):
            result["accounts"].append({
                "domain": acct.get("domain", ""),
                "url": acct.get("url", ""),
                "name": acct.get("shortname", ""),
            })

    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# GitHub email lookup
# ---------------------------------------------------------------------------

def check_github_email(email: str) -> dict:
    """Search GitHub for an account associated with the email.

    Returns:
        {
            "found": bool,
            "username": str or None,
            "profile_url": str or None,
            "repos_committed_to": list[str],
            "commit_count": int,
            "error": str or None,
        }
    """
    result = {
        "found": False,
        "username": None,
        "profile_url": None,
        "repos_committed_to": [],
        "commit_count": 0,
        "error": None,
    }

    # Strategy 1: Search users by email
    try:
        resp = requests.get(
            "https://api.github.com/search/users",
            params={"q": f"{email} in:email"},
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("total_count", 0) > 0:
                user = data["items"][0]
                result["found"] = True
                result["username"] = user.get("login")
                result["profile_url"] = user.get("html_url")
                return result
    except Exception:
        pass

    time.sleep(0.5)

    # Strategy 2: Search commits by author email
    try:
        resp = requests.get(
            "https://api.github.com/search/commits",
            params={"q": f"author-email:{email}"},
            headers={"Accept": "application/vnd.github.cloak-preview+json"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("total_count", 0) > 0:
                result["found"] = True
                result["commit_count"] = data["total_count"]

                # Extract username from first commit's author
                first_item = data["items"][0]
                author = first_item.get("author")
                if author:
                    result["username"] = author.get("login")
                    result["profile_url"] = author.get("html_url")

                # Collect unique repos
                seen_repos = set()
                for item in data["items"][:10]:
                    repo = item.get("repository", {}).get("full_name")
                    if repo:
                        seen_repos.add(repo)
                result["repos_committed_to"] = list(seen_repos)

    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# Search engine helpers (duplicated from discovery.py per module convention)
# ---------------------------------------------------------------------------

def _search_google(query: str, max_results: int = 10) -> list[str]:
    """Search Google and return result URLs."""
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
                if href.startswith("/url?q="):
                    actual_url = href.split("/url?q=")[1].split("&")[0]
                    if actual_url.startswith(("http://", "https://")):
                        urls.append(actual_url)
                        if len(urls) >= max_results:
                            break
    except Exception:
        pass
    return urls


def _search_duckduckgo(query: str, max_results: int = 10) -> list[str]:
    """Search DuckDuckGo HTML and return result URLs."""
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


# ---------------------------------------------------------------------------
# Web search for person
# ---------------------------------------------------------------------------

def search_person_by_email(
    email: str,
    name_candidates: list[dict],
    domain: str = "",
    progress_callback=None,
) -> dict:
    """Search the web for profiles associated with the email and name.

    Returns:
        {
            "linkedin_profile": str or None,
            "other_profiles": list[dict],
            "mentions": list[dict],
            "best_name": str or None,
        }
    """
    result = {
        "linkedin_profile": None,
        "other_profiles": [],
        "mentions": [],
        "best_name": None,
    }

    seen_urls = set()

    def _classify_url(url: str) -> str | None:
        hostname = (urlparse(url).hostname or "").lower()
        if "linkedin.com" in hostname:
            return "linkedin"
        if "twitter.com" in hostname or "x.com" in hostname:
            return "twitter"
        if "facebook.com" in hostname:
            return "facebook"
        if "instagram.com" in hostname:
            return "instagram"
        if "github.com" in hostname:
            return "github"
        return None

    def _process_urls(urls: list[str], source: str):
        for url in urls:
            clean_url = url.split("?")[0].rstrip("/")
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            platform = _classify_url(url)
            if platform == "linkedin" and "/in/" in url and not result["linkedin_profile"]:
                result["linkedin_profile"] = clean_url
            elif platform and platform != "linkedin":
                result["other_profiles"].append({
                    "url": clean_url,
                    "platform": platform,
                    "source": source,
                })
            else:
                result["mentions"].append({
                    "url": clean_url,
                    "source": source,
                })

    # Search 1: Direct email search
    if progress_callback:
        progress_callback("Searching web for email...")

    query = f'"{email}"'
    urls = _search_google(query)
    if not urls:
        time.sleep(0.3)
        urls = _search_duckduckgo(query)
    _process_urls(urls, "email_search")
    time.sleep(0.3)

    # Search 2: Name-based LinkedIn search (high/medium confidence candidates)
    good_candidates = [c for c in name_candidates if c["confidence"] in ("high", "medium")]
    if not good_candidates and name_candidates:
        good_candidates = name_candidates[:1]

    for candidate in good_candidates[:2]:
        first = candidate["first"]
        last = candidate["last"]
        if not last:
            continue

        full_name = f"{first} {last}"

        if progress_callback:
            progress_callback(f"Searching for {full_name} on LinkedIn...")

        query = f'"{full_name}" site:linkedin.com/in'
        urls = _search_google(query, max_results=5)
        if not urls:
            time.sleep(0.3)
            urls = _search_duckduckgo(query, max_results=5)
        _process_urls(urls, "name_linkedin_search")
        time.sleep(0.3)

        # Search 3: Name + company domain association
        if domain:
            query = f'"{full_name}" "{domain}"'
            urls = _search_google(query, max_results=5)
            if not urls:
                time.sleep(0.3)
                urls = _search_duckduckgo(query, max_results=5)
            _process_urls(urls, "name_domain_search")
            time.sleep(0.3)

        # Use this candidate as best_name if we found a LinkedIn match
        if result["linkedin_profile"] and not result["best_name"]:
            result["best_name"] = full_name

    # If no best_name yet, use the highest confidence candidate
    if not result["best_name"] and good_candidates:
        c = good_candidates[0]
        if c["last"]:
            result["best_name"] = f"{c['first']} {c['last']}"

    return result


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def gather_email_person_intel(email: str, progress_callback=None) -> dict:
    """Run all email-based person lookups and return consolidated results.

    Returns:
        {
            "email": str,
            "valid": bool,
            "domain": str,
            "local_part": str,
            "name_candidates": list[dict],
            "best_name": str or None,
            "gravatar": dict,
            "github": dict,
            "linkedin_profile": str or None,
            "other_profiles": list[dict],
            "mentions": list[dict],
            "person_score": float,
            "flags": list[str],
        }
    """
    validation = validate_email(email)
    if not validation["valid"]:
        return {
            "email": email,
            "valid": False,
            "domain": "",
            "local_part": "",
            "name_candidates": [],
            "best_name": None,
            "gravatar": {"found": False},
            "github": {"found": False},
            "linkedin_profile": None,
            "other_profiles": [],
            "mentions": [],
            "person_score": 0,
            "flags": ["Invalid email format"],
        }

    domain = validation["domain"]
    local_part = validation["local_part"]

    # Extract name candidates
    name_info = extract_name_from_email(local_part)
    candidates = name_info["candidates"]

    # Gravatar lookup
    if progress_callback:
        progress_callback("Checking Gravatar...")
    gravatar = check_gravatar(email)
    time.sleep(0.3)

    # If Gravatar has a display name, prepend it as a high-confidence candidate
    if gravatar.get("display_name"):
        grav_name = gravatar["display_name"]
        parts = grav_name.split(None, 1)
        if len(parts) == 2:
            candidates.insert(0, {
                "first": parts[0],
                "last": parts[1],
                "confidence": "high",
                "pattern": "gravatar",
            })

    # Add any Gravatar-linked profiles to results
    gravatar_profiles = []
    for acct in gravatar.get("accounts", []):
        if acct.get("url"):
            gravatar_profiles.append({
                "url": acct["url"],
                "platform": acct.get("name", "unknown"),
                "source": "gravatar",
            })

    # GitHub email lookup
    if progress_callback:
        progress_callback("Checking GitHub for email...")
    github = check_github_email(email)
    time.sleep(0.3)

    # Web search for person
    search_result = search_person_by_email(
        email, candidates, domain=domain, progress_callback=progress_callback
    )

    # Merge profiles
    other_profiles = gravatar_profiles + search_result["other_profiles"]
    if github.get("found") and github.get("profile_url"):
        seen = {p["url"] for p in other_profiles}
        if github["profile_url"] not in seen:
            other_profiles.append({
                "url": github["profile_url"],
                "platform": "github",
                "source": "github_api",
            })

    # Deduplicate
    seen_urls = set()
    unique_profiles = []
    for p in other_profiles:
        url = p["url"].rstrip("/")
        if url not in seen_urls:
            seen_urls.add(url)
            unique_profiles.append(p)

    # Best name: prefer search result, then Gravatar, then candidates
    best_name = search_result.get("best_name")
    if not best_name and gravatar.get("display_name"):
        best_name = gravatar["display_name"]
    if not best_name and candidates:
        c = candidates[0]
        if c["last"]:
            best_name = f"{c['first']} {c['last']}"

    # Compute person score (0-100)
    person_score = 0.0
    flags = []

    if gravatar.get("found"):
        person_score += 20
        name_str = f" ({gravatar['display_name']})" if gravatar.get("display_name") else ""
        flags.append(f"Gravatar profile found{name_str}")

    if search_result.get("linkedin_profile"):
        person_score += 25
        flags.append(f"LinkedIn profile found: {search_result['linkedin_profile']}")

    if github.get("found"):
        person_score += 20
        commit_str = f" ({github['commit_count']} commits)" if github.get("commit_count") else ""
        repo_count = len(github.get("repos_committed_to", []))
        repo_str = f" across {repo_count} repo(s)" if repo_count else ""
        flags.append(f"GitHub account: {github.get('username', 'unknown')}{commit_str}{repo_str}")

    # Extra profiles bonus (max 20)
    extra_count = len(unique_profiles)
    person_score += min(extra_count * 10, 20)
    if extra_count > 0:
        flags.append(f"{extra_count} additional social profile(s) found")

    # Name identified
    if best_name:
        person_score += 5
        flags.insert(0, f"Identified as: {best_name}")

    if person_score == 0:
        flags.append("No digital footprint found for this email address")

    person_score = min(person_score, 100)

    return {
        "email": email,
        "valid": True,
        "domain": domain,
        "local_part": local_part,
        "name_candidates": candidates,
        "best_name": best_name,
        "gravatar": gravatar,
        "github": github,
        "linkedin_profile": search_result.get("linkedin_profile"),
        "other_profiles": unique_profiles,
        "mentions": search_result.get("mentions", []),
        "person_score": round(person_score, 1),
        "flags": flags,
    }
