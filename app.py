"""Social Media Presence & Legitimacy Verification App.

Enter a company domain or email address to automatically:
  1. Discover social media profiles (from the company's own website first)
  2. Verify each profile (URL resolves, domain referenced, account age)
  3. Check reviews across Google, BBB, Trustpilot, Glassdoor, G2, Yelp, Capterra
  4. Detect developer/startup signals (GitHub, npm, Product Hunt, Crunchbase, app stores)
  5. Assess domain intelligence (WHOIS age, DNS, historical DNS, website analysis)
  6. Compute a risk score (0-100) mapped to Low / Medium / High / Critical tiers
  7. Find employee profiles and fetch latest posts
  8. (Email mode) Look up the person behind the email — name, LinkedIn, social profiles
"""

import json
import re
from datetime import date, datetime

import streamlit as st

from utils.url_checker import check_url_resolves, detect_platform
from utils.scraper import scrape_profile, check_domain_in_profile
from utils.date_checker import extract_creation_indicators, check_predates_denial
from utils.discovery import discover_social_profiles, discover_employees
from utils.post_fetcher import fetch_latest_post
from utils.domain_intel import get_domain_age, scrape_website_social_links, check_dns_records, check_historical_dns
from utils.reviews import discover_reviews, calculate_review_score
from utils.tech_signals import gather_all_tech_signals, calculate_tech_score
from utils.risk_engine import calculate_overall_risk
from utils.email_intel import validate_email, gather_email_person_intel

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Social Media & Legitimacy Verification",
    page_icon="🔍",
    layout="wide",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
.main-header { font-size: 2rem; font-weight: 700; margin-bottom: 0.2rem; }
.sub-header { color: #666; font-size: 1rem; margin-bottom: 1.5rem; }
.check-pass { background: #d4edda; border: 1px solid #c3e6cb; border-radius: 8px; padding: 0.6rem 0.8rem; margin-bottom: 0.3rem; }
.check-fail { background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 8px; padding: 0.6rem 0.8rem; margin-bottom: 0.3rem; }
.check-warn { background: #fff3cd; border: 1px solid #ffeeba; border-radius: 8px; padding: 0.6rem 0.8rem; margin-bottom: 0.3rem; }
.check-info { background: #d1ecf1; border: 1px solid #bee5eb; border-radius: 8px; padding: 0.6rem 0.8rem; margin-bottom: 0.3rem; }
.risk-badge { display: inline-block; padding: 0.4rem 1.2rem; border-radius: 20px; color: white; font-weight: 700; font-size: 1rem; }
.score-ring { text-align: center; padding: 1.5rem; }
.score-number { font-size: 3.5rem; font-weight: 800; line-height: 1; }
.score-label { font-size: 1rem; color: #666; margin-top: 0.3rem; }
.section-card { border: 1px solid #e0e0e0; border-radius: 10px; padding: 1rem; margin-bottom: 0.8rem; background: #fafafa; }
.post-card { border-left: 4px solid #0077b5; padding: 0.6rem 0.8rem; margin: 0.4rem 0; background: #f8f9fa; border-radius: 0 8px 8px 0; font-size: 0.9rem; }
.flag-item { padding: 0.3rem 0; border-bottom: 1px solid #eee; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown('<div class="main-header">Social Media & Legitimacy Verification</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">'
    "Enter a company domain or email address to run a full legitimacy assessment: "
    "social profiles, reviews, developer signals, domain intelligence, and risk scoring."
    "</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
input_mode = st.radio(
    "Input type",
    ["Company Domain", "Email Address"],
    horizontal=True,
    help="Domain mode assesses the company. Email mode also identifies the person behind the email.",
)

col_input, col_date = st.columns([3, 1])
with col_input:
    if input_mode == "Company Domain":
        raw_input = st.text_input(
            "Company Domain",
            placeholder="example.com",
            help="We'll scan the website, discover social profiles, check reviews, and assess risk.",
        )
    else:
        raw_input = st.text_input(
            "Email Address",
            placeholder="name@example.com",
            help="We'll identify the person, extract the company domain, and run the full assessment.",
        )
with col_date:
    denial_date = st.date_input(
        "Denial Date (optional)",
        value=date.today(),
        help="Used to check if social accounts predate this date.",
    )

run_btn = st.button("Run Full Assessment", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
if run_btn and raw_input and raw_input.strip():
    email_address = None
    email_intel_result = None

    # --- Parse input ---
    if input_mode == "Email Address":
        validation = validate_email(raw_input.strip())
        if not validation["valid"]:
            st.error(f"Invalid email: {validation['error']}")
            st.stop()
        email_address = validation["email"]
        domain = validation["domain"]
    else:
        domain = raw_input.strip().lower()
        if domain.startswith(("http://", "https://")):
            domain = domain.split("//", 1)[1]
        if domain.startswith("www."):
            domain = domain[4:]
        domain = domain.rstrip("/")

    company_name = domain.split(".")[0].replace("-", " ").replace("_", " ").title()

    progress_bar = st.progress(0)
    status = st.empty()

    def update(msg, pct=None):
        status.caption(msg)
        if pct is not None:
            progress_bar.progress(pct)

    # ==================================================================
    # PHASE 1: Domain Intelligence
    # ==================================================================
    update("Analyzing domain...", 5)

    website_info = scrape_website_social_links(domain)
    whois_info = get_domain_age(domain)
    dns_info = check_dns_records(domain)

    update("Checking web archive history...", 10)
    historical_dns = check_historical_dns(domain)

    domain_intel = {
        "website": website_info,
        "whois": whois_info,
        "dns": dns_info,
        "historical_dns": historical_dns,
    }

    # ==================================================================
    # PHASE 2: Social Profile Discovery & Verification
    # ==================================================================
    update("Discovering social profiles...", 15)

    profiles = discover_social_profiles(
        domain,
        website_social_links=website_info.get("social_links", {}),
        progress_callback=lambda m: update(m),
    )

    update("Verifying profiles...", 30)

    social_results = {}
    for platform_key, profile_info in profiles.items():
        url = profile_info["url"]
        platform = platform_key

        url_result = check_url_resolves(url)

        if url_result["resolved"]:
            profile_data = scrape_profile(url_result["html"], platform)
            domain_result = check_domain_in_profile(profile_data, domain)
            date_info = extract_creation_indicators(url, url_result["html"], platform)
            denial_comparison = check_predates_denial(date_info["creation_date"], denial_date)
            post = fetch_latest_post(url, url_result["html"], platform)
        else:
            profile_data = {}
            domain_result = {"found": False, "locations": [], "confidence": "low"}
            date_info = {}
            denial_comparison = {"predates": None, "message": "Skipped — URL did not resolve."}
            post = {"found": False}

        social_results[profile_info["label"]] = {
            "url": url,
            "platform": platform,
            "label": profile_info["label"],
            "source": profile_info["source"],
            "url_check": url_result,
            "domain_check": domain_result,
            "date_check": {**date_info, **denial_comparison},
            "latest_post": post,
            "profile_data": profile_data,
        }

    # ==================================================================
    # PHASE 3: Reviews
    # ==================================================================
    update("Checking review platforms...", 45)

    reviews = discover_reviews(
        domain, company_name, progress_callback=lambda m: update(m)
    )
    review_score = calculate_review_score(reviews)

    # ==================================================================
    # PHASE 4: Tech / Startup Signals
    # ==================================================================
    update("Checking developer & startup signals...", 60)

    tech_signals = gather_all_tech_signals(
        domain, company_name, progress_callback=lambda m: update(m)
    )
    tech_score = calculate_tech_score(tech_signals)

    # ==================================================================
    # PHASE 5: Employee Discovery
    # ==================================================================
    update("Searching for employee profiles...", 75)

    employees = discover_employees(domain, company_name, progress_callback=lambda m: update(m))

    # ==================================================================
    # PHASE 6: Person Intelligence (email mode only)
    # ==================================================================
    if email_address:
        update("Looking up person associated with email...", 85)
        email_intel_result = gather_email_person_intel(
            email_address, progress_callback=lambda m: update(m)
        )

    # ==================================================================
    # PHASE 7: Risk Calculation
    # ==================================================================
    update("Calculating risk score...", 95)

    risk = calculate_overall_risk(
        social_results=social_results,
        review_score=review_score,
        tech_score=tech_score,
        domain_info=domain_intel,
        denial_date=denial_date,
        email_intel=email_intel_result,
    )

    update("Assessment complete.", 100)

    # ==================================================================
    # DISPLAY RESULTS
    # ==================================================================
    st.markdown("---")

    # --- Risk Score Hero ---
    tier_color = risk["tier_info"]["color"]
    tier_label = risk["tier_info"]["label"]

    hero_col1, hero_col2, hero_col3 = st.columns([1, 1, 2])

    with hero_col1:
        st.markdown(
            f'<div class="score-ring">'
            f'<div class="score-number" style="color: {tier_color};">{risk["overall_score"]}</div>'
            f'<div class="score-label">Risk Score (0-100)</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

    with hero_col2:
        st.markdown(
            f'<div class="score-ring">'
            f'<div><span class="risk-badge" style="background: {tier_color};">{tier_label}</span></div>'
            f'<div class="score-label" style="margin-top: 0.8rem;">'
            f'{risk["tier_info"]["description"]}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

    with hero_col3:
        st.markdown("**Assessment Summary**")
        st.markdown(risk["recommendation"])
        if email_address:
            st.info(f"Email mode: assessing **{email_address}** (domain: {domain})")
        if risk.get("maturity") == "established":
            st.success("Identified as an established tech company. Standard scoring weights applied — social presence and reviews are expected.")
        elif risk["is_startup"]:
            st.info("Detected as an early-stage startup. Risk weights adjusted to account for typically lower social media presence in new companies.")

    # --- Score Breakdown ---
    st.markdown("---")
    st.subheader("Score Breakdown")

    labels = {
        "social": "Social Media",
        "reviews": "Reviews",
        "tech": "Tech Signals",
        "domain": "Domain Intel",
        "account_age": "Account Age",
    }
    if "person" in risk["breakdown"]:
        labels["person"] = "Person"

    breakdown_cols = st.columns(len(labels))
    for i, (key, label) in enumerate(labels.items()):
        bd = risk["breakdown"][key]
        with breakdown_cols[i]:
            score_val = bd["score"]
            weight_pct = int(bd["weight"] * 100)
            color = "#28a745" if score_val >= 60 else "#ffc107" if score_val >= 35 else "#dc3545"
            st.markdown(
                f"**{label}**  \n"
                f'<span style="font-size: 1.8rem; font-weight: 700; color: {color};">'
                f"{score_val:.0f}</span>"
                f'<span style="color: #999; font-size: 0.8rem;"> /100 ({weight_pct}% weight)</span>',
                unsafe_allow_html=True,
            )

    # --- Flags ---
    if risk["flags"]:
        st.markdown("---")
        st.subheader("Flags & Findings")
        for flag in risk["flags"]:
            if any(w in flag.lower() for w in ["concern", "weak", "limited", "no review", "no tech", "too new", "poor rating", "below-average", "mediocre", "red flag", "no digital footprint", "no web archive"]):
                icon = "&#10060;"
            elif any(w in flag.lower() for w in ["startup", "adjusted"]):
                icon = "&#9888;&#65039;"
            else:
                icon = "&#9989;"
            st.markdown(f'<div class="flag-item">{icon} {flag}</div>', unsafe_allow_html=True)

    # --- Person Intelligence (email mode only) ---
    if email_intel_result and email_intel_result.get("valid"):
        st.markdown("---")
        st.subheader("Person Intelligence")
        st.caption(f"Email analyzed: {email_intel_result['email']}")

        pi_col1, pi_col2 = st.columns(2)

        with pi_col1:
            st.markdown("**Identity**")
            if email_intel_result.get("best_name"):
                st.markdown(
                    f'<div class="check-pass">&#9989; Likely name: <b>{email_intel_result["best_name"]}</b></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="check-warn">&#9888;&#65039; Could not determine name from email</div>',
                    unsafe_allow_html=True,
                )

            if email_intel_result.get("linkedin_profile"):
                st.markdown(
                    f'<div class="check-pass">&#9989; LinkedIn: '
                    f'<a href="{email_intel_result["linkedin_profile"]}">'
                    f'{email_intel_result["linkedin_profile"]}</a></div>',
                    unsafe_allow_html=True,
                )

            grav = email_intel_result.get("gravatar", {})
            if grav.get("found"):
                display = f" — {grav['display_name']}" if grav.get("display_name") else ""
                st.markdown(
                    f'<div class="check-pass">&#9989; Gravatar profile found{display}</div>',
                    unsafe_allow_html=True,
                )

        with pi_col2:
            st.markdown("**Digital Footprint**")
            gh = email_intel_result.get("github", {})
            if gh.get("found"):
                commit_str = f" ({gh['commit_count']} commits)" if gh.get("commit_count") else ""
                st.markdown(
                    f'<div class="check-pass">&#9989; GitHub: '
                    f'<a href="{gh.get("profile_url", "#")}">{gh.get("username", "unknown")}</a>'
                    f'{commit_str}</div>',
                    unsafe_allow_html=True,
                )

            for profile in email_intel_result.get("other_profiles", []):
                st.markdown(
                    f'<div class="check-info">{profile["platform"].title()}: '
                    f'<a href="{profile["url"]}">{profile["url"]}</a></div>',
                    unsafe_allow_html=True,
                )

            if (
                not email_intel_result.get("linkedin_profile")
                and not gh.get("found")
                and not grav.get("found")
                and not email_intel_result.get("other_profiles")
            ):
                st.markdown(
                    '<div class="check-fail">&#10060; No digital footprint found for this email</div>',
                    unsafe_allow_html=True,
                )

        st.markdown(
            f"**Person Verification Score:** {email_intel_result.get('person_score', 0)}/100"
        )

    # --- Domain Intelligence ---
    st.markdown("---")
    st.subheader("Domain Intelligence")

    di_col1, di_col2, di_col3, di_col4 = st.columns(4)

    with di_col1:
        st.markdown("**WHOIS Data**")
        if whois_info.get("creation_date"):
            age_years = (whois_info.get("age_days") or 0) / 365
            st.markdown(f'<div class="check-pass">Registered: {whois_info["creation_date"]} ({age_years:.1f} years)</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="check-warn">WHOIS data unavailable</div>', unsafe_allow_html=True)
        if whois_info.get("registrar"):
            st.caption(f"Registrar: {whois_info['registrar']}")

    with di_col2:
        st.markdown("**DNS**")
        if dns_info.get("resolves"):
            st.markdown('<div class="check-pass">Domain resolves</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="check-fail">Domain does not resolve</div>', unsafe_allow_html=True)
        if dns_info.get("has_mx"):
            st.markdown('<div class="check-pass">Has email (MX records)</div>', unsafe_allow_html=True)

    with di_col3:
        st.markdown("**Website**")
        if website_info.get("website_reachable"):
            st.markdown('<div class="check-pass">Website is live</div>', unsafe_allow_html=True)
            link_count = len(website_info.get("social_links", {}))
            if link_count:
                st.markdown(f'<div class="check-info">{link_count} social link(s) found on site</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="check-fail">Website unreachable</div>', unsafe_allow_html=True)

    with di_col4:
        st.markdown("**Web Archive**")
        if historical_dns.get("found"):
            years = historical_dns.get("years_of_history") or 0
            count = historical_dns.get("snapshot_count", 0)
            earliest = historical_dns.get("earliest_snapshot", "unknown")
            css = "check-pass" if years >= 2 else "check-warn" if years >= 0.5 else "check-fail"
            st.markdown(
                f'<div class="{css}">First seen: {earliest}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="{css}">{years:.1f} years of history ({count} snapshots)</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown('<div class="check-warn">No web archive history found</div>', unsafe_allow_html=True)

    # --- Social Media Profiles ---
    st.markdown("---")
    st.subheader("Social Media Profiles")

    if not social_results:
        st.warning("No social media profiles discovered.")
    else:
        for label, r in social_results.items():
            with st.expander(f"{label} — {r['url']}", expanded=True):
                st.caption(f"Found via: {r['source']}")

                if r["url_check"]["resolved"]:
                    st.markdown(f'<div class="check-pass">&#9989; URL Resolves (Status {r["url_check"]["status_code"]})</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="check-fail">&#10060; URL Does Not Resolve — {r["url_check"]["error"]}</div>', unsafe_allow_html=True)
                    continue

                # Follower count
                followers = r.get("profile_data", {}).get("followers")
                if followers is not None:
                    if followers >= 10_000:
                        st.markdown(f'<div class="check-pass">&#9989; <b>{followers:,} followers</b> — strong audience</div>', unsafe_allow_html=True)
                    elif followers >= 1_000:
                        st.markdown(f'<div class="check-pass">&#9989; <b>{followers:,} followers</b> — established audience</div>', unsafe_allow_html=True)
                    elif followers >= 100:
                        st.markdown(f'<div class="check-info">&#128101; <b>{followers:,} followers</b> — growing audience</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="check-warn">&#128101; <b>{followers:,} followers</b> — limited audience</div>', unsafe_allow_html=True)

                dc = r["domain_check"]
                if dc["found"]:
                    locs = ", ".join(dc["locations"][:3])
                    css = "check-pass" if dc["confidence"] == "high" else "check-warn"
                    st.markdown(f'<div class="{css}">&#9989; Domain referenced (confidence: {dc["confidence"]}) — {locs}</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="check-fail">&#10060; Domain not found in profile</div>', unsafe_allow_html=True)

                dtc = r["date_check"]
                if dtc.get("predates") is True:
                    st.markdown(f'<div class="check-pass">&#9989; {dtc["message"]}</div>', unsafe_allow_html=True)
                elif dtc.get("predates") is False:
                    st.markdown(f'<div class="check-fail">&#10060; {dtc["message"]}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="check-warn">&#9888;&#65039; {dtc.get("message", "Age uncertain")}</div>', unsafe_allow_html=True)

                post = r["latest_post"]
                if post.get("found") and post.get("text"):
                    display = post["text"][:250] + ("..." if len(post["text"]) > 250 else "")
                    st.markdown("**Latest Post:**")
                    st.markdown(f'<div class="post-card">{display}</div>', unsafe_allow_html=True)
                    if post.get("source"):
                        st.caption(f"Source: {post['source']}")

    # --- Associated Properties ---
    # Aggregate company website, external links, and app references from all profiles + website
    associated_properties = []
    linkedin_website = None
    seen_assoc_domains = set()

    def _extract_brand(d: str) -> str:
        """Extract brand name from domain (e.g., 'mytraffic' from 'mytraffic.fr')."""
        import re as _re
        d = _re.sub(r"^www\.", "", d.lower())
        parts = d.split(".")
        # For subdomains like app.mytraffic.io, use the second-level part
        if len(parts) >= 3:
            return parts[-2]
        return parts[0] if parts else d

    primary_brand = _extract_brand(domain)

    def _is_connected(ext_domain: str) -> bool:
        """Check if an external domain is connected to the primary domain."""
        ext_lower = ext_domain.lower()
        # Direct substring match
        if domain in ext_lower or ext_lower in domain:
            return True
        # Brand name appears anywhere in the external domain
        # (catches mytraffic.teamtailor.com, app.mytraffic.io, etc.)
        if primary_brand and len(primary_brand) >= 4 and primary_brand in ext_lower:
            return True
        # Brand name match (e.g., mytraffic.fr ↔ mytraffic.io)
        ext_brand = _extract_brand(ext_domain)
        if primary_brand and ext_brand and (primary_brand in ext_brand or ext_brand in primary_brand):
            return True
        return False

    for label, r in social_results.items():
        pd = r.get("profile_data", {})

        # LinkedIn company website
        cw = pd.get("company_website")
        if cw and not linkedin_website:
            linkedin_website = cw

        # External links from each profile
        for ext in pd.get("external_links", []):
            ext_domain = ext["domain"]
            if ext_domain not in seen_assoc_domains:
                seen_assoc_domains.add(ext_domain)
                associated_properties.append({
                    **ext,
                    "found_on": label,
                    "connected": _is_connected(ext_domain),
                })

    # External links found on the company website itself
    for ext in website_info.get("external_links", []):
        ext_domain = ext["domain"]
        if ext_domain not in seen_assoc_domains:
            seen_assoc_domains.add(ext_domain)
            associated_properties.append({
                **ext,
                "found_on": "Company website",
                "connected": _is_connected(ext_domain),
            })

    # Also check if LinkedIn website domain differs from primary domain
    if linkedin_website:
        lw_parsed = linkedin_website.split("//")[-1].split("/")[0].lower()
        lw_parsed = re.sub(r"^www\.", "", lw_parsed)
        if lw_parsed not in seen_assoc_domains and lw_parsed != domain:
            seen_assoc_domains.add(lw_parsed)
            associated_properties.insert(0, {
                "url": linkedin_website,
                "domain": lw_parsed,
                "type": "website",
                "found_on": "LinkedIn (company website)",
                "connected": _is_connected(lw_parsed),
            })

    if linkedin_website or associated_properties:
        st.markdown("---")
        st.subheader("Associated Properties")

        if linkedin_website:
            lw_domain = linkedin_website.split("//")[-1].split("/")[0].lower().replace("www.", "")
            if lw_domain == domain or domain in lw_domain:
                st.markdown(
                    f'<div class="check-pass">&#127760; <b>LinkedIn Company Website:</b> '
                    f'<a href="{linkedin_website}">{linkedin_website}</a> — matches primary domain</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="check-warn">&#127760; <b>LinkedIn Company Website:</b> '
                    f'<a href="{linkedin_website}">{linkedin_website}</a> — '
                    f'different from primary domain ({domain})</div>',
                    unsafe_allow_html=True,
                )

        if associated_properties:
            connected = [p for p in associated_properties if p["connected"]]
            not_connected = [p for p in associated_properties if not p["connected"]]

            if connected:
                st.markdown("**Connected to primary domain:**")
                for prop in connected:
                    st.markdown(
                        f'<div class="check-pass">&#128279; <b>{prop["domain"]}</b> '
                        f'— <a href="{prop["url"]}">{prop["url"]}</a> '
                        f'(found on {prop["found_on"]})</div>',
                        unsafe_allow_html=True,
                    )

            if not_connected:
                st.markdown("**Other associated domains:**")
                for prop in not_connected:
                    st.markdown(
                        f'<div class="check-info">&#128279; <b>{prop["domain"]}</b> '
                        f'— <a href="{prop["url"]}">{prop["url"]}</a> '
                        f'(found on {prop["found_on"]})</div>',
                        unsafe_allow_html=True,
                    )

    # --- Reviews ---
    st.markdown("---")
    st.subheader("Reviews")

    found_reviews = {k: v for k, v in reviews.items() if v["found"]}
    not_found = {k: v for k, v in reviews.items() if not v["found"]}

    # Show average rating summary if available
    if review_score.get("average_rating") is not None:
        avg = review_score["average_rating"]
        avg_css = "check-pass" if avg >= 4.0 else "check-warn" if avg >= 3.0 else "check-fail"
        st.markdown(
            f'<div class="{avg_css}">&#11088; <b>Average Rating: {avg:.1f}/5</b> '
            f'across {review_score["platforms_with_ratings"]} platform(s) '
            f'{"— strong signal" if avg >= 4.0 else "— below 4 stars, weighed negatively" if avg < 4.0 else ""}'
            f'</div>',
            unsafe_allow_html=True,
        )

    if found_reviews:
        for key, rev in found_reviews.items():
            rating_str = ""
            css_class = "check-pass"
            if rev.get("rating"):
                rating_str = f" — Rating: {rev['rating']}"
                try:
                    rating_val = float(str(rev["rating"]).replace(",", ".").split("/")[0].strip())
                    if rating_val >= 4.0:
                        css_class = "check-pass"
                    elif rating_val >= 3.0:
                        css_class = "check-warn"
                    else:
                        css_class = "check-fail"
                except (ValueError, IndexError):
                    pass
            count_str = f" ({rev['review_count']} reviews)" if rev.get("review_count") else ""
            st.markdown(
                f'<div class="{css_class}">{rev["icon"]} <b>{rev["label"]}</b>{rating_str}{count_str} '
                f'— <a href="{rev["url"]}">View</a></div>',
                unsafe_allow_html=True,
            )
            if rev.get("summary"):
                st.caption(rev["summary"][:150])
    else:
        st.info("No reviews found on any platform.")

    if not_found:
        with st.expander(f"Not found on {len(not_found)} platform(s)"):
            for key, rev in not_found.items():
                st.caption(f"{rev['icon']} {rev['label']} — Not found")

    # --- Tech / Startup Signals ---
    st.markdown("---")
    st.subheader("Developer & Startup Signals")

    if tech_score["is_likely_tech_company"]:
        st.success(f"Likely tech/startup company — {tech_score['signals_found']} signal(s) detected")

    gh = tech_signals.get("github", {})
    if gh.get("found"):
        st.markdown(
            f'<div class="check-pass">&#9989; <b>GitHub</b> — '
            f'<a href="{gh["url"]}">{gh["org_name"]}</a> '
            f'({gh.get("public_repos", 0)} repos, {gh.get("followers", 0)} followers)</div>',
            unsafe_allow_html=True,
        )
        if gh.get("description"):
            st.caption(gh["description"])

    npm = tech_signals.get("npm", {})
    if npm.get("found"):
        pkgs = ", ".join(p["name"] for p in npm.get("packages", [])[:3])
        st.markdown(f'<div class="check-pass">&#9989; <b>npm</b> — Packages: {pkgs}</div>', unsafe_allow_html=True)

    ph = tech_signals.get("product_hunt", {})
    if ph.get("found"):
        st.markdown(f'<div class="check-pass">&#9989; <b>Product Hunt</b> — <a href="{ph["url"]}">{ph.get("product_name", "View")}</a></div>', unsafe_allow_html=True)

    cb = tech_signals.get("crunchbase", {})
    if cb.get("found"):
        st.markdown(f'<div class="check-pass">&#9989; <b>Crunchbase</b> — <a href="{cb["url"]}">Profile</a></div>', unsafe_allow_html=True)
        if cb.get("summary"):
            st.caption(cb["summary"][:150])

    apps = tech_signals.get("app_stores", {})
    if apps.get("apple", {}).get("found"):
        st.markdown(f'<div class="check-pass">&#9989; <b>Apple App Store</b> — {apps["apple"].get("app_name", "Listed")}</div>', unsafe_allow_html=True)
    if apps.get("google", {}).get("found"):
        st.markdown(f'<div class="check-pass">&#9989; <b>Google Play</b> — {apps["google"].get("app_name", "Listed")}</div>', unsafe_allow_html=True)

    so = tech_signals.get("stack_overflow", {})
    if so.get("found"):
        st.markdown(f'<div class="check-pass">&#9989; <b>Stack Overflow</b> — {so.get("type", "presence")}</div>', unsafe_allow_html=True)

    tb = tech_signals.get("tech_blog", {})
    if tb.get("found"):
        st.markdown(f'<div class="check-pass">&#9989; <b>{tb.get("type", "Blog").replace("_", " ").title()}</b> — <a href="{tb["url"]}">{tb["url"]}</a></div>', unsafe_allow_html=True)

    if tech_score["signals_found"] == 0:
        st.info("No developer or startup signals found.")

    # --- Employees ---
    st.markdown("---")
    st.subheader("Employee Profiles")

    if employees:
        st.success(f"Found {len(employees)} employee profile(s)")
        for emp in employees:
            title_str = f" — {emp['title']}" if emp.get("title") else ""
            st.markdown(f"**{emp['name']}**{title_str} — [{emp['url']}]({emp['url']})")
    else:
        st.info("No employee profiles discovered via search.")

    # --- Export ---
    st.markdown("---")
    export_data = {
        "domain": domain,
        "company_name": company_name,
        "denial_date": denial_date.isoformat(),
        "assessment_date": datetime.now().isoformat(),
        "input_mode": input_mode.lower().replace(" ", "_"),
        "risk": {
            "overall_score": risk["overall_score"],
            "tier": risk["tier"],
            "tier_label": risk["tier_info"]["label"],
            "is_startup": risk["is_startup"],
            "recommendation": risk["recommendation"],
            "breakdown": {
                k: {"score": round(v["score"], 1), "weight": v["weight"]}
                for k, v in risk["breakdown"].items()
            },
            "flags": risk["flags"],
        },
        "domain_intel": {
            "whois": {
                "creation_date": str(whois_info.get("creation_date")),
                "age_days": whois_info.get("age_days"),
                "registrar": whois_info.get("registrar"),
            },
            "dns_resolves": dns_info.get("resolves"),
            "has_mx": dns_info.get("has_mx"),
            "website_reachable": website_info.get("website_reachable"),
            "social_links_on_site": website_info.get("social_links", {}),
            "historical_dns": {
                "found": historical_dns.get("found", False),
                "earliest_snapshot": historical_dns.get("earliest_snapshot"),
                "latest_snapshot": historical_dns.get("latest_snapshot"),
                "years_of_history": historical_dns.get("years_of_history"),
                "snapshot_count": historical_dns.get("snapshot_count", 0),
            },
        },
        "social_profiles": {
            label: {
                "url": r["url"],
                "platform": r["platform"],
                "source": r["source"],
                "url_resolved": r["url_check"]["resolved"],
                "domain_found": r["domain_check"]["found"],
                "domain_confidence": r["domain_check"]["confidence"],
                "predates_denial": r["date_check"].get("predates"),
                "latest_post_found": r["latest_post"].get("found", False),
                "latest_post_text": r["latest_post"].get("text", "")[:300] if r["latest_post"].get("text") else None,
            }
            for label, r in social_results.items()
        },
        "associated_properties": {
            "linkedin_website": linkedin_website,
            "external_links": associated_properties,
        },
        "reviews": {
            key: {
                "found": rev["found"],
                "url": rev.get("url"),
                "rating": rev.get("rating"),
                "review_count": rev.get("review_count"),
            }
            for key, rev in reviews.items()
        },
        "review_score": review_score,
        "tech_signals": {
            "github_found": tech_signals.get("github", {}).get("found", False),
            "github_repos": tech_signals.get("github", {}).get("public_repos"),
            "npm_found": tech_signals.get("npm", {}).get("found", False),
            "product_hunt_found": tech_signals.get("product_hunt", {}).get("found", False),
            "crunchbase_found": tech_signals.get("crunchbase", {}).get("found", False),
            "app_store_apple": tech_signals.get("app_stores", {}).get("apple", {}).get("found", False),
            "app_store_google": tech_signals.get("app_stores", {}).get("google", {}).get("found", False),
            "stack_overflow_found": tech_signals.get("stack_overflow", {}).get("found", False),
            "tech_blog_found": tech_signals.get("tech_blog", {}).get("found", False),
        },
        "tech_score": tech_score,
        "employees": employees,
    }

    # Add email-specific data to export
    if email_intel_result:
        export_data["email_input"] = email_address
        export_data["person_intel"] = {
            "best_name": email_intel_result.get("best_name"),
            "linkedin_profile": email_intel_result.get("linkedin_profile"),
            "gravatar_found": email_intel_result.get("gravatar", {}).get("found", False),
            "gravatar_display_name": email_intel_result.get("gravatar", {}).get("display_name"),
            "github_found": email_intel_result.get("github", {}).get("found", False),
            "github_username": email_intel_result.get("github", {}).get("username"),
            "other_profiles": email_intel_result.get("other_profiles", []),
            "person_score": email_intel_result.get("person_score", 0),
            "flags": email_intel_result.get("flags", []),
        }

    st.download_button(
        label="Download Full Assessment Report (JSON)",
        data=json.dumps(export_data, indent=2, default=str),
        file_name=f"assessment_{domain.replace('.', '_')}_{date.today().isoformat()}.json",
        mime="application/json",
        use_container_width=True,
    )

elif run_btn:
    st.error("Please enter a company domain or email address.")
