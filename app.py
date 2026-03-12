"""Social Media Presence Verification App.

A Streamlit application that takes a company domain and automatically:
  1. Discovers social media profiles (LinkedIn, Facebook, Twitter/X, Instagram)
  2. Verifies each profile (URL resolves, domain referenced, account age)
  3. Finds employee profiles linked to the company
  4. Fetches and displays the latest post from each profile
"""

import json
from datetime import date, datetime

import streamlit as st

from utils.url_checker import check_url_resolves, detect_platform
from utils.scraper import scrape_profile, check_domain_in_profile
from utils.date_checker import extract_creation_indicators, check_predates_denial
from utils.discovery import discover_social_profiles, discover_employees
from utils.post_fetcher import fetch_latest_post

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Social Media Presence Verification",
    page_icon="🔍",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: 0.25rem;
    }
    .sub-header {
        color: #666;
        font-size: 1.05rem;
        margin-bottom: 1.5rem;
    }
    .check-pass {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 8px;
        padding: 0.8rem 1rem;
        margin-bottom: 0.4rem;
    }
    .check-fail {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        border-radius: 8px;
        padding: 0.8rem 1rem;
        margin-bottom: 0.4rem;
    }
    .check-warn {
        background-color: #fff3cd;
        border: 1px solid #ffeeba;
        border-radius: 8px;
        padding: 0.8rem 1rem;
        margin-bottom: 0.4rem;
    }
    .overall-pass {
        background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
        color: white; padding: 1.5rem; border-radius: 12px;
        text-align: center; font-size: 1.3rem; font-weight: 700;
    }
    .overall-fail {
        background: linear-gradient(135deg, #dc3545 0%, #e83e8c 100%);
        color: white; padding: 1.5rem; border-radius: 12px;
        text-align: center; font-size: 1.3rem; font-weight: 700;
    }
    .overall-review {
        background: linear-gradient(135deg, #ffc107 0%, #fd7e14 100%);
        color: white; padding: 1.5rem; border-radius: 12px;
        text-align: center; font-size: 1.3rem; font-weight: 700;
    }
    .platform-card {
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 1.2rem;
        margin-bottom: 1rem;
        background: #fafafa;
    }
    .employee-card {
        border: 1px solid #e8e8e8;
        border-radius: 8px;
        padding: 0.8rem 1rem;
        margin-bottom: 0.5rem;
        background: white;
    }
    .post-card {
        border-left: 4px solid #0077b5;
        padding: 0.8rem 1rem;
        margin: 0.5rem 0;
        background: #f8f9fa;
        border-radius: 0 8px 8px 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="main-header">Social Media Presence Verification</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-header">'
    "Enter a company domain to automatically discover social profiles, "
    "verify legitimacy, find employee profiles, and surface recent posts."
    "</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Input — just the domain + optional denial date
# ---------------------------------------------------------------------------
col_input, col_date = st.columns([3, 1])

with col_input:
    domain = st.text_input(
        "Company Domain",
        placeholder="example.com",
        help="The company's primary website domain. We'll search for all associated social profiles.",
    )

with col_date:
    denial_date = st.date_input(
        "Denial Date (optional)",
        value=date.today(),
        help="If provided, we'll check whether accounts were created before this date.",
    )

run_btn = st.button("Scan & Verify", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Main verification flow
# ---------------------------------------------------------------------------
if run_btn and domain and domain.strip():
    domain = domain.strip().lower()
    # Strip protocol / www if pasted
    if domain.startswith(("http://", "https://")):
        domain = domain.split("//", 1)[1]
    if domain.startswith("www."):
        domain = domain[4:]
    domain = domain.rstrip("/")

    company_name = domain.split(".")[0].replace("-", " ").replace("_", " ").title()

    # -----------------------------------------------------------------------
    # Phase 1: Discover social profiles
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("Phase 1 — Profile Discovery")
    progress_text = st.empty()
    progress_bar = st.progress(0)

    def update_progress(msg: str):
        progress_text.caption(msg)

    profiles = discover_social_profiles(domain, progress_callback=update_progress)
    progress_bar.progress(30)

    if not profiles:
        st.warning(
            f"No social media profiles found for **{domain}**. "
            "Try checking the domain spelling or entering a more specific domain."
        )
        st.stop()

    st.success(f"Found **{len(profiles)}** social media profile(s) for **{domain}**")

    for key, info in profiles.items():
        st.markdown(
            f"&nbsp;&nbsp;&nbsp; **{info['label']}** — [{info['url']}]({info['url']}) "
            f"*(found via {info['source']})*"
        )

    # -----------------------------------------------------------------------
    # Phase 2: Verify each profile
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("Phase 2 — Profile Verification")
    progress_bar.progress(40)

    all_results = {}
    platform_idx = 0
    total_platforms = len(profiles)

    for platform_key, profile_info in profiles.items():
        platform_idx += 1
        url = profile_info["url"]
        label = profile_info["label"]

        pct = 40 + int((platform_idx / total_platforms) * 30)
        progress_bar.progress(pct)
        update_progress(f"Verifying {label}...")

        st.markdown(f'<div class="platform-card">', unsafe_allow_html=True)
        st.markdown(f"#### {label}")
        st.caption(f"[{url}]({url})")

        result = {"url": url, "platform": platform_key, "label": label}

        # --- Check 1: URL resolves ---
        url_result = check_url_resolves(url)
        result["url_check"] = url_result

        if url_result["resolved"]:
            st.markdown(
                f'<div class="check-pass">&#9989; <b>URL Resolves</b> — '
                f'Status {url_result["status_code"]}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="check-fail">&#10060; <b>URL Does Not Resolve</b> — '
                f'{url_result["error"]}</div>',
                unsafe_allow_html=True,
            )
            result["domain_check"] = {"found": False, "locations": [], "confidence": "low"}
            result["date_check"] = {"predates": None, "message": "Skipped — URL did not resolve."}
            result["latest_post"] = {"found": False}
            all_results[label] = result
            st.markdown("</div>", unsafe_allow_html=True)
            continue

        # --- Check 2: Domain reference ---
        profile_data = scrape_profile(url_result["html"], platform_key)
        domain_result = check_domain_in_profile(profile_data, domain)
        result["domain_check"] = domain_result

        if domain_result["found"]:
            loc_list = ", ".join(domain_result["locations"][:5])
            if domain_result["confidence"] == "high":
                st.markdown(
                    f'<div class="check-pass">&#9989; <b>Domain Referenced</b> '
                    f'(confidence: high) — {loc_list}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="check-warn">&#9888;&#65039; <b>Domain Referenced</b> '
                    f'(confidence: {domain_result["confidence"]}) — {loc_list}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                f'<div class="check-fail">&#10060; <b>Domain Not Found</b> — '
                f'<code>{domain}</code> not detected in profile</div>',
                unsafe_allow_html=True,
            )

        # --- Check 3: Account age ---
        date_info = extract_creation_indicators(url, url_result["html"], platform_key)
        denial_comparison = check_predates_denial(date_info["creation_date"], denial_date)
        result["date_check"] = {**date_info, **denial_comparison}

        if denial_comparison["predates"] is True:
            st.markdown(
                f'<div class="check-pass">&#9989; <b>Predates Denial</b> — '
                f'{denial_comparison["message"]}</div>',
                unsafe_allow_html=True,
            )
        elif denial_comparison["predates"] is False:
            st.markdown(
                f'<div class="check-fail">&#10060; <b>Created After Denial</b> — '
                f'{denial_comparison["message"]}</div>',
                unsafe_allow_html=True,
            )
        else:
            extra = ""
            if date_info.get("earliest_snapshot"):
                extra = f" (earliest Wayback snapshot: {date_info['earliest_snapshot'].isoformat()})"
            st.markdown(
                f'<div class="check-warn">&#9888;&#65039; <b>Age Uncertain</b> — '
                f'{denial_comparison["message"]}{extra}</div>',
                unsafe_allow_html=True,
            )

        # --- Latest post ---
        update_progress(f"Fetching latest post from {label}...")
        post = fetch_latest_post(url, url_result["html"], platform_key)
        result["latest_post"] = post

        if post["found"]:
            st.markdown("**Latest Post:**")
            post_html = f'<div class="post-card">'
            if post.get("date"):
                post_html += f'<small><b>{post["date"]}</b></small><br>'
            if post.get("text"):
                # Truncate for display
                display_text = post["text"][:300]
                if len(post["text"]) > 300:
                    display_text += "..."
                post_html += f"{display_text}"
            if post.get("url"):
                post_html += f'<br><small><a href="{post["url"]}">View post</a></small>'
            post_html += "</div>"
            st.markdown(post_html, unsafe_allow_html=True)
            if post.get("source"):
                st.caption(f"Source: {post['source']}")
        else:
            st.caption("No recent posts found (page may require JavaScript to load content).")

        # Expandable raw data
        with st.expander("Raw scraped data"):
            st.json({
                "title": profile_data.get("title", ""),
                "description": profile_data.get("description", ""),
                "bio_text": profile_data.get("bio_text", "")[:500],
                "links_found": profile_data.get("links_found", [])[:20],
                "og_data": profile_data.get("og_data", {}),
            })

        st.markdown("</div>", unsafe_allow_html=True)
        all_results[label] = result

    # -----------------------------------------------------------------------
    # Phase 3: Employee discovery
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("Phase 3 — Employee Profiles")
    progress_bar.progress(75)
    update_progress("Searching for employee profiles...")

    employees = discover_employees(domain, company_name)
    progress_bar.progress(90)

    if employees:
        st.success(f"Found **{len(employees)}** employee profile(s)")
        for emp in employees:
            title_str = f" — {emp['title']}" if emp.get("title") else ""
            st.markdown(
                f'<div class="employee-card">'
                f'<b>{emp["name"]}</b>{title_str}<br>'
                f'<small><a href="{emp["url"]}">{emp["url"]}</a></small>'
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        st.info("No employee profiles discovered. This may be due to search engine limitations.")

    # -----------------------------------------------------------------------
    # Phase 4: Overall verdict
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("Overall Verification Result")
    progress_bar.progress(100)
    progress_text.caption("Verification complete.")

    total_checks = 0
    passed_checks = 0
    failed_checks = 0
    uncertain_checks = 0

    for label, r in all_results.items():
        total_checks += 1
        if r["url_check"]["resolved"]:
            passed_checks += 1
        else:
            failed_checks += 1

        total_checks += 1
        if r["domain_check"]["found"] and r["domain_check"]["confidence"] == "high":
            passed_checks += 1
        elif r["domain_check"]["found"]:
            uncertain_checks += 1
        else:
            failed_checks += 1

        total_checks += 1
        if r["date_check"].get("predates") is True:
            passed_checks += 1
        elif r["date_check"].get("predates") is False:
            failed_checks += 1
        else:
            uncertain_checks += 1

    if failed_checks == 0 and uncertain_checks == 0:
        st.markdown(
            '<div class="overall-pass">PASS — All checks passed</div>',
            unsafe_allow_html=True,
        )
    elif failed_checks > 0:
        st.markdown(
            f'<div class="overall-fail">FAIL — {failed_checks} of {total_checks} checks failed</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="overall-review">NEEDS REVIEW — '
            f"{uncertain_checks} of {total_checks} checks need manual review</div>",
            unsafe_allow_html=True,
        )

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Profiles Found", len(profiles))
    col_b.metric("Checks Passed", f"{passed_checks}/{total_checks}")
    col_c.metric("Checks Failed", f"{failed_checks}/{total_checks}")
    col_d.metric("Employees Found", len(employees))

    # -----------------------------------------------------------------------
    # Export
    # -----------------------------------------------------------------------
    st.markdown("---")
    export_data = {
        "domain": domain,
        "company_name": company_name,
        "denial_date": denial_date.isoformat(),
        "verification_date": datetime.now().isoformat(),
        "profiles": {},
        "employees": employees,
        "summary": {
            "profiles_found": len(profiles),
            "total_checks": total_checks,
            "passed": passed_checks,
            "failed": failed_checks,
            "uncertain": uncertain_checks,
        },
    }
    for label, r in all_results.items():
        export_data["profiles"][label] = {
            "url": r["url"],
            "platform": r["platform"],
            "url_resolved": r["url_check"]["resolved"],
            "status_code": r["url_check"]["status_code"],
            "domain_found": r["domain_check"]["found"],
            "domain_confidence": r["domain_check"]["confidence"],
            "domain_locations": r["domain_check"].get("locations", []),
            "account_predates_denial": r["date_check"].get("predates"),
            "creation_date": (
                str(r["date_check"].get("creation_date"))
                if r["date_check"].get("creation_date")
                else None
            ),
            "date_source": r["date_check"].get("source"),
            "latest_post": {
                "found": r["latest_post"]["found"],
                "text": r["latest_post"].get("text"),
                "date": r["latest_post"].get("date"),
                "source": r["latest_post"].get("source"),
            },
        }

    st.download_button(
        label="Download Full Report (JSON)",
        data=json.dumps(export_data, indent=2, default=str),
        file_name=f"social_verification_{domain.replace('.', '_')}_{date.today().isoformat()}.json",
        mime="application/json",
        use_container_width=True,
    )

elif run_btn:
    st.error("Please enter a company domain to scan.")
