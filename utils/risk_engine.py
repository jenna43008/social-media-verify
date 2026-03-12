"""Risk scoring engine.

Combines signals from social media, reviews, tech presence, and domain
intelligence into a single risk score (0-100) mapped to tiers.
"""

from datetime import date, datetime

from dateutil import parser as dateutil_parser


# Risk tiers
TIERS = {
    "LOW": {"min": 70, "label": "Low Risk", "color": "#28a745", "description": "Strong legitimacy signals across multiple dimensions."},
    "MEDIUM": {"min": 45, "label": "Medium Risk", "color": "#ffc107", "description": "Some legitimacy signals present but gaps remain."},
    "HIGH": {"min": 25, "label": "High Risk", "color": "#fd7e14", "description": "Limited legitimacy signals. Enhanced due diligence recommended."},
    "CRITICAL": {"min": 0, "label": "Critical Risk", "color": "#dc3545", "description": "Very few or no legitimacy signals found. Manual investigation required."},
}


def calculate_overall_risk(
    social_results: dict,
    review_score: dict,
    tech_score: dict,
    domain_info: dict,
    denial_date: date | None = None,
    email_intel: dict | None = None,
) -> dict:
    """Calculate the overall risk score and tier.

    Weights (domain mode):
      - Social media presence:  25%
      - Reviews:                20%
      - Tech/developer signals: 20%
      - Domain intelligence:    20%
      - Account age vs denial:  15%

    When email_intel is provided, a "person" dimension is added:
      - Social: 20%, Reviews: 18%, Tech: 18%, Domain: 17%, Age: 12%, Person: 15%

    For detected tech/startup companies, weights shift to value tech
    signals more and social media less.

    Returns:
        {
            "overall_score": float (0-100),
            "tier": str ("LOW", "MEDIUM", "HIGH", "CRITICAL"),
            "tier_info": dict,
            "breakdown": {
                "social": {"score": float, "weight": float, "weighted": float},
                "reviews": {...},
                "tech": {...},
                "domain": {...},
                "account_age": {...},
                "person": {...},  # only when email_intel provided
            },
            "flags": list[str],
            "is_startup": bool,
            "recommendation": str,
        }
    """
    maturity = tech_score.get("maturity", "non_tech")
    is_early_stage = maturity == "early_stage"
    has_person = email_intel is not None and email_intel.get("valid", False)

    # Weight adjustments based on company maturity and input mode.
    if has_person:
        if is_early_stage:
            weights = {
                "social": 0.12, "reviews": 0.12, "tech": 0.25,
                "domain": 0.17, "account_age": 0.14, "person": 0.20,
            }
        else:
            weights = {
                "social": 0.20, "reviews": 0.18, "tech": 0.18,
                "domain": 0.17, "account_age": 0.12, "person": 0.15,
            }
    elif is_early_stage:
        weights = {
            "social": 0.15, "reviews": 0.15, "tech": 0.30,
            "domain": 0.20, "account_age": 0.20,
        }
    else:
        weights = {
            "social": 0.25, "reviews": 0.20, "tech": 0.20,
            "domain": 0.20, "account_age": 0.15,
        }

    # --- Social media score ---
    social_score = _calculate_social_score(social_results)

    # --- Review score (already calculated) ---
    review_val = review_score.get("score", 0)

    # --- Tech score (already calculated) ---
    tech_val = tech_score.get("score", 0)

    # --- Domain score ---
    domain_score = _calculate_domain_score(domain_info)

    # --- Account age score ---
    age_score = _calculate_age_score(social_results, denial_date)

    # Weighted total
    breakdown = {
        "social": {
            "score": social_score,
            "weight": weights["social"],
            "weighted": social_score * weights["social"],
        },
        "reviews": {
            "score": review_val,
            "weight": weights["reviews"],
            "weighted": review_val * weights["reviews"],
        },
        "tech": {
            "score": tech_val,
            "weight": weights["tech"],
            "weighted": tech_val * weights["tech"],
        },
        "domain": {
            "score": domain_score,
            "weight": weights["domain"],
            "weighted": domain_score * weights["domain"],
        },
        "account_age": {
            "score": age_score,
            "weight": weights["account_age"],
            "weighted": age_score * weights["account_age"],
        },
    }

    # --- Person score (email mode only) ---
    if has_person:
        person_val = email_intel.get("person_score", 0)
        breakdown["person"] = {
            "score": person_val,
            "weight": weights["person"],
            "weighted": person_val * weights["person"],
        }

    overall = sum(b["weighted"] for b in breakdown.values())

    # Determine tier
    tier = "CRITICAL"
    for t_name, t_info in TIERS.items():
        if overall >= t_info["min"]:
            tier = t_name
            break

    # Collect all flags — descriptive and specific
    flags = []
    flags.extend(review_score.get("flags", []))
    flags.extend(tech_score.get("flags", []))

    # Domain age flag (include actual age when available)
    if domain_score < 30:
        whois = domain_info.get("whois", {})
        age_days = whois.get("age_days")
        if age_days is not None:
            age_years = age_days / 365
            if age_years < 1:
                flags.append(f"Domain registered only {age_days} days ago — very new")
            else:
                flags.append(f"Domain registered {age_years:.1f} years ago — raises concerns")
        else:
            flags.append("Domain age or WHOIS data unavailable — raises concerns")

    # Social presence flag (include count)
    total_profiles = len(social_results)
    if social_score < 20:
        flags.append(f"Only {total_profiles} of 7 social platforms found — very weak presence")
    elif total_profiles == 1:
        platform_name = list(social_results.keys())[0] if social_results else "unknown"
        flags.append(f"Only 1 social profile found ({platform_name}) — limited presence")

    if age_score < 30 and social_results:
        flags.append("Social accounts may have been created after denial date — possibly reactionary")

    # Follower count flags
    max_followers = 0
    for label, r in social_results.items():
        followers = r.get("profile_data", {}).get("followers")
        if followers and followers > max_followers:
            max_followers = followers

    if max_followers >= 10_000:
        flags.append(f"Strong social following ({max_followers:,} followers)")
    elif max_followers >= 1_000:
        flags.append(f"Established social following ({max_followers:,} followers)")
    elif max_followers > 0 and max_followers < 100:
        flags.append(f"Very small social following ({max_followers:,} followers)")

    # Posting activity flags — recency-aware and per-platform
    post_details = []
    most_recent_days = None
    most_recent_platform = None
    stale_platforms = []

    for label, r in social_results.items():
        post = r.get("latest_post", {})
        if post.get("found"):
            days = _days_since_post(post.get("date"))
            if days is not None:
                post_details.append((label, days))
                if most_recent_days is None or days < most_recent_days:
                    most_recent_days = days
                    most_recent_platform = label
                if days > 180:
                    stale_platforms.append((label, days))
            else:
                post_details.append((label, None))

    if most_recent_days is not None:
        recency = _describe_recency(most_recent_days)
        if most_recent_days < 30:
            flags.append(f"Recent posting activity: {most_recent_platform} ({recency})")
        elif most_recent_days < 90:
            flags.append(f"Moderate posting activity: last post on {most_recent_platform} ({recency})")
        elif most_recent_days < 365:
            flags.append(f"Infrequent posting: last post on {most_recent_platform} ({recency})")
        else:
            flags.append(f"Stale posting activity: last post on {most_recent_platform} ({recency})")
    elif post_details:
        # Posts found but no dates parseable
        flags.append("Posting activity detected (dates unavailable)")
    elif social_results:
        flags.append("No posts found on any platform — accounts may be inactive or private")

    # Flag significant gaps: platforms with stale posts while others are active
    for plat, days in stale_platforms:
        if most_recent_days is not None and days - most_recent_days > 180:
            flags.append(f"Significant gap: {plat} last posted {_describe_recency(days)} while {most_recent_platform} posted {_describe_recency(most_recent_days)}")

    # Startup / maturity flag (include what triggered it)
    if is_early_stage:
        gh = tech_score.get("signals", {}).get("github", {}) if isinstance(tech_score.get("signals"), dict) else {}
        signals_found = tech_score.get("signals_found", 0)
        detail_parts = []
        if signals_found:
            detail_parts.append(f"{signals_found} tech signal{'s' if signals_found != 1 else ''}")
        flags.insert(0, f"Detected as early-stage startup ({', '.join(detail_parts) if detail_parts else 'limited tech presence'}) — weights adjusted")
    elif maturity == "established":
        flags.insert(0, "Established tech company — standard weights applied across all dimensions")

    # Person flags (email mode)
    if has_person:
        flags.extend(email_intel.get("flags", []))

    # Historical DNS flags
    hist_dns = domain_info.get("historical_dns", {})
    if hist_dns.get("found"):
        years = hist_dns.get("years_of_history") or 0
        count = hist_dns.get("snapshot_count", 0)
        if years >= 5:
            flags.append(f"Strong web archive history ({years:.0f} years, {count} snapshots)")
        elif years >= 1:
            flags.append(f"Web archive history: {years:.1f} years ({count} snapshots)")
        else:
            flags.append(f"Limited web archive history ({count} snapshots)")
    else:
        flags.append("No web archive history found — domain may be very new")

    # Generate recommendation
    recommendation = _generate_recommendation(overall, tier, is_early_stage, maturity, flags, breakdown)

    return {
        "overall_score": round(overall, 1),
        "tier": tier,
        "tier_info": TIERS[tier],
        "breakdown": breakdown,
        "flags": flags,
        "is_startup": is_early_stage,
        "maturity": maturity,
        "recommendation": recommendation,
    }


def _calculate_social_score(social_results: dict) -> float:
    """Score social media presence (0-100).

    Factors:
      - Number of profiles found
      - URL resolves, domain referenced, latest post found
      - LinkedIn follower count (strong legitimacy signal)
      - Posting activity (recent posts = active, engaged company)
    """
    if not social_results:
        return 0

    score = 0.0
    total_profiles = len(social_results)

    # Points for number of profiles found (max 20)
    if total_profiles >= 4:
        score += 20
    elif total_profiles >= 3:
        score += 16
    elif total_profiles >= 2:
        score += 12
    elif total_profiles >= 1:
        score += 6

    # Points for verification results per profile
    for label, r in social_results.items():
        if r.get("url_check", {}).get("resolved"):
            score += 3

        domain_check = r.get("domain_check", {})
        if domain_check.get("found"):
            if domain_check.get("confidence") == "high":
                score += 8
            elif domain_check.get("confidence") == "medium":
                score += 4
            else:
                score += 2

        # Posting activity: recency-aware scoring
        post = r.get("latest_post", {})
        if post.get("found"):
            days_ago = _days_since_post(post.get("date"))
            if days_ago is not None:
                if days_ago < 7:
                    score += 15
                elif days_ago < 30:
                    score += 12
                elif days_ago < 90:
                    score += 8
                elif days_ago < 180:
                    score += 4
                elif days_ago < 365:
                    score += 2
                # > 365 days: stale, no bonus
            else:
                # Post found but date unknown — moderate bonus
                score += 5

    # LinkedIn follower count bonus (strong legitimacy signal)
    # Look across all profiles for the highest follower count
    max_followers = 0
    for label, r in social_results.items():
        followers = r.get("profile_data", {}).get("followers")
        if followers and followers > max_followers:
            max_followers = followers

    if max_followers >= 100_000:
        score += 25  # major brand
    elif max_followers >= 10_000:
        score += 20  # well-established
    elif max_followers >= 1_000:
        score += 14  # growing presence
    elif max_followers >= 100:
        score += 8   # small but real
    elif max_followers >= 10:
        score += 3   # minimal

    return min(score, 100)


def _days_since_post(date_str: str | None) -> int | None:
    """Calculate the number of days between a post date and today."""
    if not date_str:
        return None
    try:
        dt = dateutil_parser.parse(str(date_str), fuzzy=True)
        delta = datetime.now() - dt.replace(tzinfo=None)
        return max(0, delta.days)
    except (ValueError, OverflowError, TypeError):
        return None


def _describe_recency(days: int) -> str:
    """Convert days-ago into a human-readable recency label."""
    if days < 1:
        return "today"
    elif days == 1:
        return "yesterday"
    elif days < 7:
        return f"{days} days ago"
    elif days < 30:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    elif days < 365:
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    else:
        years = days / 365
        return f"{years:.1f} years ago"


def _calculate_domain_score(domain_info: dict) -> float:
    """Score domain legitimacy (0-100)."""
    score = 0.0

    # Website reachable
    website_info = domain_info.get("website", {})
    if website_info.get("website_reachable"):
        score += 20

    # Social links on website (strong signal)
    social_links = website_info.get("social_links", {})
    if len(social_links) >= 3:
        score += 25
    elif len(social_links) >= 2:
        score += 18
    elif len(social_links) >= 1:
        score += 10

    # Domain age
    whois_info = domain_info.get("whois", {})
    age_days = whois_info.get("age_days")
    if age_days is not None:
        if age_days >= 365 * 5:  # 5+ years
            score += 30
        elif age_days >= 365 * 2:  # 2-5 years
            score += 25
        elif age_days >= 365:  # 1-2 years
            score += 18
        elif age_days >= 180:  # 6-12 months
            score += 12
        elif age_days >= 90:  # 3-6 months
            score += 6
        else:
            score += 2  # very new domain

    # DNS resolves
    dns_info = domain_info.get("dns", {})
    if dns_info.get("resolves"):
        score += 5
    if dns_info.get("has_mx"):
        score += 10  # has email infrastructure

    # Registrar (known registrars add confidence)
    if whois_info.get("registrar"):
        score += 5

    # Historical DNS (Wayback Machine snapshots)
    hist_dns = domain_info.get("historical_dns", {})
    if hist_dns.get("found"):
        years = hist_dns.get("years_of_history") or 0
        if years >= 10:
            score += 15
        elif years >= 5:
            score += 12
        elif years >= 2:
            score += 8
        elif years >= 1:
            score += 4
        else:
            score += 2

    return min(score, 100)


def _calculate_age_score(social_results: dict, denial_date: date | None) -> float:
    """Score based on how account ages compare to the denial date."""
    if not denial_date or not social_results:
        return 50  # neutral if no denial date

    score = 50.0  # start neutral
    has_data = False

    for label, r in social_results.items():
        date_check = r.get("date_check", {})
        predates = date_check.get("predates")

        if predates is True:
            score += 20
            has_data = True
        elif predates is False:
            score -= 25
            has_data = True

    if not has_data:
        return 40  # slightly below neutral if we couldn't determine

    return max(0, min(score, 100))


def _generate_recommendation(
    score: float, tier: str, is_early_stage: bool, maturity: str,
    flags: list, breakdown: dict,
) -> str:
    """Generate a human-readable recommendation."""
    parts = []

    if tier == "LOW":
        parts.append(
            "This entity shows strong legitimacy indicators across multiple dimensions."
        )
        if maturity == "established":
            parts.append(
                "Identified as an established tech company with strong digital presence."
            )
        elif is_early_stage:
            parts.append(
                "Despite being an early-stage startup, it has established "
                "verifiable digital presence."
            )
        parts.append("Standard processing is recommended.")

    elif tier == "MEDIUM":
        parts.append(
            "This entity shows moderate legitimacy signals with some gaps."
        )
        weakest = min(breakdown.items(), key=lambda x: x[1]["score"])
        parts.append(
            f"The weakest area is {weakest[0]} (score: {weakest[1]['score']:.0f}/100)."
        )
        if is_early_stage:
            parts.append(
                "Note: This appears to be an early-stage startup. Limited social presence "
                "is common for new companies — tech signals have been weighted higher."
            )
        parts.append("Targeted follow-up on flagged areas is recommended.")

    elif tier == "HIGH":
        parts.append(
            "This entity shows limited legitimacy signals. Enhanced due diligence "
            "is strongly recommended."
        )
        if is_early_stage:
            parts.append(
                "Even with early-stage startup adjustments, legitimacy signals are sparse."
            )
        weak_areas = [
            k for k, v in breakdown.items() if v["score"] < 30
        ]
        if weak_areas:
            parts.append(
                f"Areas of concern: {', '.join(weak_areas)}."
            )
        parts.append("Request additional documentation before proceeding.")

    else:  # CRITICAL
        parts.append(
            "Very few or no legitimacy signals were found for this entity. "
            "This does not necessarily indicate fraud, but requires thorough "
            "manual investigation."
        )
        parts.append(
            "Consider requesting business registration documents, tax ID, "
            "bank references, or other hard evidence of business legitimacy."
        )

    return " ".join(parts)
