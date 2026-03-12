"""Social Media Presence & Legitimacy Verification App.

Enter a company domain to automatically:
  1. Discover social media profiles (from the company's own website first)
  2. Verify each profile (URL resolves, domain referenced, account age)
  3. Check reviews across Google, BBB, Trustpilot, Glassdoor, G2, Yelp, Capterra
  4. Detect developer/startup signals (GitHub, npm, Product Hunt, Crunchbase, app stores)
  5. Assess domain intelligence (WHOIS age, DNS, website analysis)
  6. Compute a risk score (0-100) mapped to Low / Medium / High / Critical tiers
  7. Find employee profiles and fetch latest posts
"""

import json
from datetime import date, datetime

import streamlit as st

from utils.url_checker import check_url_resolves, detect_platform
from utils.scraper import scrape_profile, check_domain_in_profile
from utils.date_checker import extract_creation_indicators, check_predates_denial
from utils.discovery import discover_social_profiles, discover_employees
from utils.post_fetcher import fetch_latest_post
from utils.domain_intel import get_domain_age, scrape_website_social_links, check_dns_records
from utils.reviews import discover_reviews, calculate_review_score
from utils.tech_signals import gather_all_tech_signals, calculate_tech_score
from utils.risk_engine import calculate_overall_risk

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
    "Enter a company domain to run a full legitimacy assessment: social profiles, "
    "reviews, developer signals, domain intelligence, and risk scoring."
    "</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
col_input, col_date = st.columns([3, 1])
with col_input:
    domain = st.text_input(
        "Company Domain",
        placeholder="example.com",
        help="We'll scan the website, discover social profiles, check reviews, and assess risk.",
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
if run_btn and domain and domain.strip():
    domain = domain.strip().lower()
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

    domain_intel = {"website": website_info, "whois": whois_info, "dns": dns_info}

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
    update("Searching for employee profiles...", 80)

    employees = discover_employees(domain, company_name, progress_callback=lambda m: update(m))

    # ==================================================================
    # PHASE 6: Risk Calculation
    # ==================================================================
    update("Calculating risk score...", 90)

    risk = calculate_overall_risk(
        social_results=social_results,
        review_score=review_score,
        tech_score=tech_score,
        domain_info=domain_intel,
        denial_date=denial_date,
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
        if risk.get("maturity") == "established":
            st.success("Identified as an established tech company. Standard scoring weights applied — social presence and reviews are expected.")
        elif risk["is_startup"]:
            st.info("Detected as an early-stage startup. Risk weights adjusted to account for typically lower social media presence in new companies.")

    # --- Score Breakdown ---
    st.markdown("---")
    st.subheader("Score Breakdown")

    breakdown_cols = st.columns(5)
    labels = {
        "social": "Social Media",
        "reviews": "Reviews",
        "tech": "Tech Signals",
        "domain": "Domain Intel",
        "account_age": "Account Age",
    }
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
            if any(w in flag.lower() for w in ["concern", "weak", "limited", "no review", "no tech", "too new"]):
                icon = "&#10060;"
            elif any(w in flag.lower() for w in ["startup", "adjusted"]):
                icon = "&#9888;&#65039;"
            else:
                icon = "&#9989;"
            st.markdown(f'<div class="flag-item">{icon} {flag}</div>', unsafe_allow_html=True)

    # --- Domain Intelligence ---
    st.markdown("---")
    st.subheader("Domain Intelligence")

    di_col1, di_col2, di_col3 = st.columns(3)

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

    # --- Reviews ---
    st.markdown("---")
    st.subheader("Reviews")

    found_reviews = {k: v for k, v in reviews.items() if v["found"]}
    not_found = {k: v for k, v in reviews.items() if not v["found"]}

    if found_reviews:
        for key, rev in found_reviews.items():
            rating_str = f" — Rating: {rev['rating']}" if rev.get("rating") else ""
            count_str = f" ({rev['review_count']} reviews)" if rev.get("review_count") else ""
            st.markdown(
                f'<div class="check-pass">{rev["icon"]} <b>{rev["label"]}</b>{rating_str}{count_str} '
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

    st.download_button(
        label="Download Full Assessment Report (JSON)",
        data=json.dumps(export_data, indent=2, default=str),
        file_name=f"assessment_{domain.replace('.', '_')}_{date.today().isoformat()}.json",
        mime="application/json",
        use_container_width=True,
    )

elif run_btn:
    st.error("Please enter a company domain.")
