"""Fetch the most recent post from social media profiles."""

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

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


def _normalize_post_date(raw_date: str | None) -> str | None:
    """Parse a raw date string into ISO format (YYYY-MM-DD).

    Returns None if the date can't be parsed.
    """
    if not raw_date:
        return None
    try:
        dt = dateutil_parser.parse(str(raw_date), fuzzy=True)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError, TypeError):
        return raw_date  # return as-is if unparseable


def fetch_latest_post(url: str, html: str | None, platform: str) -> dict:
    """Attempt to extract the most recent post from a social media profile.

    Strategies vary by platform — many rely on meta tags, structured data,
    or RSS feeds since JS-rendered content isn't accessible via requests.

    Returns:
        {
            "found": bool,
            "text": str or None,
            "date": str or None,
            "url": str or None (permalink to the post),
            "media_url": str or None,
            "source": str (how the post was found),
        }
    """
    result = {
        "found": False,
        "text": None,
        "date": None,
        "url": None,
        "media_url": None,
        "source": None,
    }

    if not html:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            if resp.status_code < 400:
                html = resp.text
        except Exception:
            return result

    if not html:
        return result

    soup = BeautifulSoup(html, "lxml")

    # Strategy 1: JSON-LD structured data (works for many platforms)
    post = _extract_from_jsonld(soup)
    if post["found"]:
        post["date"] = _normalize_post_date(post.get("date"))
        return post

    # Strategy 2: Platform-specific extraction
    if platform == "linkedin":
        post = _extract_linkedin_post(soup, url)
    elif platform == "facebook":
        post = _extract_facebook_post(soup, url)
    elif platform == "twitter":
        post = _extract_twitter_post(soup, url)
    elif platform == "instagram":
        post = _extract_instagram_post(soup, url)

    if post["found"]:
        post["date"] = _normalize_post_date(post.get("date"))
        return post

    # Strategy 3: RSS feed check (some platforms / pages offer RSS)
    post = _check_rss_feed(url, platform)
    if post["found"]:
        post["date"] = _normalize_post_date(post.get("date"))
        return post

    # Strategy 4: Open Graph / meta tag fallback (latest shared content)
    post = _extract_from_og_tags(soup)
    if post["found"]:
        post["date"] = _normalize_post_date(post.get("date"))
        return post

    return result


def _extract_from_jsonld(soup: BeautifulSoup) -> dict:
    """Extract post data from JSON-LD structured data."""
    import json

    result = {"found": False, "text": None, "date": None, "url": None, "media_url": None, "source": None}

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]

            for item in items:
                item_type = item.get("@type", "")
                if item_type in ("SocialMediaPosting", "BlogPosting", "Article", "NewsArticle"):
                    result["found"] = True
                    result["text"] = (
                        item.get("articleBody")
                        or item.get("description")
                        or item.get("headline", "")
                    )
                    result["date"] = item.get("datePublished") or item.get("dateCreated")
                    result["url"] = item.get("url")
                    if item.get("image"):
                        img = item["image"]
                        result["media_url"] = img if isinstance(img, str) else img.get("url")
                    result["source"] = "JSON-LD structured data"
                    return result
        except (json.JSONDecodeError, TypeError):
            continue

    return result


def _extract_linkedin_post(soup: BeautifulSoup, profile_url: str) -> dict:
    """Extract latest post from a LinkedIn company page."""
    result = {"found": False, "text": None, "date": None, "url": None, "media_url": None, "source": None}

    # LinkedIn public company pages sometimes expose recent updates
    # Look for post containers
    for selector in [
        ".feed-shared-update-v2",
        ".occludable-update",
        '[data-urn*="activity"]',
        ".update-components-text",
    ]:
        posts = soup.select(selector)
        if posts:
            post_el = posts[0]
            text = post_el.get_text(separator=" ", strip=True)
            if text and len(text) > 20:
                result["found"] = True
                result["text"] = text[:500]
                result["source"] = "LinkedIn page HTML"

                # Try to find date
                time_el = post_el.find("time")
                if time_el:
                    result["date"] = time_el.get("datetime") or time_el.get_text(strip=True)

                return result

    # Fallback: check the page description which sometimes contains recent activity
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        desc = meta_desc["content"]
        if len(desc) > 50:
            result["found"] = True
            result["text"] = desc[:500]
            result["source"] = "LinkedIn meta description"

    return result


def _extract_facebook_post(soup: BeautifulSoup, profile_url: str) -> dict:
    """Extract latest post from a Facebook page."""
    result = {"found": False, "text": None, "date": None, "url": None, "media_url": None, "source": None}

    # Facebook renders most content via JS, but some data is in meta tags
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        desc = og_desc["content"]
        if len(desc) > 30:
            result["found"] = True
            result["text"] = desc[:500]
            result["source"] = "Facebook Open Graph description"

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        result["media_url"] = og_image["content"]

    # Look for post containers in HTML (limited due to JS rendering)
    for selector in [
        '[data-testid="post_message"]',
        ".userContentWrapper",
        '[role="article"]',
    ]:
        posts = soup.select(selector)
        if posts:
            text = posts[0].get_text(separator=" ", strip=True)
            if text and len(text) > 20:
                result["found"] = True
                result["text"] = text[:500]
                result["source"] = "Facebook page HTML"
                break

    return result


def _extract_twitter_post(soup: BeautifulSoup, profile_url: str) -> dict:
    """Extract latest tweet from a Twitter/X profile."""
    result = {"found": False, "text": None, "date": None, "url": None, "media_url": None, "source": None}

    # Twitter/X is heavily JS-rendered, but some data exists in meta tags
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        desc = og_desc["content"]
        if len(desc) > 10:
            result["found"] = True
            result["text"] = desc[:500]
            result["source"] = "Twitter/X Open Graph description"

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        result["media_url"] = og_image["content"]

    # Check for tweet elements (unlikely without JS but worth trying)
    for selector in [
        '[data-testid="tweetText"]',
        ".tweet-text",
        ".js-tweet-text",
    ]:
        tweets = soup.select(selector)
        if tweets:
            text = tweets[0].get_text(separator=" ", strip=True)
            if text:
                result["found"] = True
                result["text"] = text[:500]
                result["source"] = "Twitter/X page HTML"
                break

    return result


def _extract_instagram_post(soup: BeautifulSoup, profile_url: str) -> dict:
    """Extract latest post from an Instagram profile."""
    result = {"found": False, "text": None, "date": None, "url": None, "media_url": None, "source": None}

    # Instagram serves most content via JS but has OG tags
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        desc = og_desc["content"]
        if len(desc) > 10:
            result["found"] = True
            result["text"] = desc[:500]
            result["source"] = "Instagram Open Graph description"

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        result["media_url"] = og_image["content"]

    return result


def _check_rss_feed(url: str, platform: str) -> dict:
    """Check for an RSS feed on the page or common RSS URL patterns."""
    result = {"found": False, "text": None, "date": None, "url": None, "media_url": None, "source": None}

    # Some Facebook pages have RSS feeds
    rss_urls = []
    if platform == "facebook":
        # Facebook pages sometimes have RSS at /posts.rss
        rss_urls.append(url.rstrip("/") + "/posts.rss")

    for rss_url in rss_urls:
        try:
            resp = requests.get(rss_url, headers=HEADERS, timeout=10)
            if resp.status_code == 200 and ("<rss" in resp.text or "<feed" in resp.text):
                soup = BeautifulSoup(resp.text, "lxml-xml")
                item = soup.find("item") or soup.find("entry")
                if item:
                    result["found"] = True
                    title_el = item.find("title")
                    desc_el = item.find("description") or item.find("content")
                    date_el = item.find("pubDate") or item.find("published") or item.find("updated")
                    link_el = item.find("link")

                    result["text"] = (
                        desc_el.get_text(strip=True)[:500] if desc_el else
                        title_el.get_text(strip=True) if title_el else None
                    )
                    result["date"] = date_el.get_text(strip=True) if date_el else None
                    result["url"] = link_el.get_text(strip=True) if link_el else (link_el.get("href") if link_el else None)
                    result["source"] = "RSS feed"
                    return result
        except Exception:
            continue

    return result


def _extract_from_og_tags(soup: BeautifulSoup) -> dict:
    """Last resort: extract whatever info is in Open Graph tags."""
    result = {"found": False, "text": None, "date": None, "url": None, "media_url": None, "source": None}

    og_desc = soup.find("meta", property="og:description")
    og_title = soup.find("meta", property="og:title")
    og_image = soup.find("meta", property="og:image")

    text_parts = []
    if og_title and og_title.get("content"):
        text_parts.append(og_title["content"])
    if og_desc and og_desc.get("content"):
        text_parts.append(og_desc["content"])

    if text_parts:
        combined = " — ".join(text_parts)
        if len(combined) > 20:
            result["found"] = True
            result["text"] = combined[:500]
            result["source"] = "Open Graph meta tags"

    if og_image and og_image.get("content"):
        result["media_url"] = og_image["content"]

    return result
