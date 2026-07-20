#!/usr/bin/env python3
"""
Internship Agent — Tiffany Sun
Searches for new 2027 summer data analyst/scientist internships weekly,
deduplicates against existing CSV, and appends only new listings.
"""

import os
import csv
import json
import time
from datetime import datetime
from dotenv import load_dotenv
from tavily import TavilyClient
from groq import Groq

# ── CONFIG ──────────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

if not GROQ_API_KEY or not TAVILY_API_KEY:
    raise EnvironmentError(
        "Missing API keys. Make sure your .env file exists and contains "
        "GROQ_API_KEY and TAVILY_API_KEY."
    )

CSV_PATH = os.path.join(os.path.dirname(__file__), "internships", "2027_summer_data_internships.csv")

SEARCH_QUERIES = [
    '"summer 2027" "data analyst" intern undergraduate',
    '"summer 2027" "data scientist" intern undergraduate',
    '"summer 2027" analytics intern undergraduate',
    '"2027" "data analyst intern" undergraduate apply',
    '"2027" "data science intern" undergraduate apply',
    '"2027" data analytics intern site:greenhouse.io OR site:lever.co'
]

CSV_COLUMNS = [
    "Role", "Company", "Location", "Work Model", "Type",
    "Pay (est.)", "Application Status", "Tiffany's Fit",
    "Priority", "Fit Reason", "Notes", "Apply URL", "Date Found"
]

# ── HELPERS ──────────────────────────────────────────────────────────────────

def load_existing(path):
    """Load existing CSV and return a set of (role, company) keys already seen."""
    seen = set()
    rows = []
    if not os.path.exists(path):
        return seen, rows
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            key = (row.get("Role", "").strip().lower(), row.get("Company", "").strip().lower())
            seen.add(key)
    return seen, rows


def save_csv(path, rows):
    """Write all rows back to CSV."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def search_web(tavily, query):
    """Run one Tavily search and return raw results with URLs preserved."""
    try:
        result = tavily.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_answer=True,
            include_raw_content=False,
        )
        snippets = []
        for r in result.get("results", []):
            snippets.append(
                f"Title: {r.get('title','')}\n"
                f"URL: {r.get('url','')}\n"
                f"Snippet: {r.get('content','')}\n"
            )
        return "\n---\n".join(snippets)
    except Exception as e:
        print(f"  Tavily error for '{query}': {e}")
        return ""


def find_apply_url(tavily, role, company):
    """Do a targeted search for the direct application link."""
    # Use key words from role to avoid grabbing wrong postings
    role_keywords = " ".join(role.split()[:4])  # first 4 words of role title
    query = (
        f'"{company}" "{role_keywords}" 2027 intern apply '
        f'site:greenhouse.io OR site:lever.co OR site:myworkdayjobs.com '
        f'OR site:careers.google.com OR site:jobs.apple.com OR site:jobs.lever.co'
    )
    try:
        result = tavily.search(query=query, search_depth="basic", max_results=3)
        good_domains = [
            "greenhouse.io", "lever.co", "myworkdayjobs.com",
            "careers.google.com", "jobs.apple.com", "jobs.lever.co",
            "/careers/", "/jobs/", "/apply"
        ]
        for r in result.get("results", []):
            url = r.get("url", "")
            title = r.get("title", "").lower()
            # Make sure the result title loosely matches the role
            role_words = [w.lower() for w in role.split() if len(w) > 3]
            if any(w in title for w in role_words) and any(d in url for d in good_domains):
                return url
    except Exception as e:
        print(f"  URL search error: {e}")
    return ""

def clean_listing(listing):
    """Remove listings with bad URLs or too many unknowns."""
    url = listing.get("url", "")

    # Remove non-http URLs
    if url and not url.startswith("http"):
        listing["url"] = ""

    # Remove generic search/aggregator URLs
    bad_domains = [
        "google.com/search", "bing.com/search", "jobright.ai",
        "ziprecruiter.com/s", "indeed.com/jobs", "linkedin.com/jobs/search",
        "glassdoor.com/Job", "simplyhired.com/search"
    ]
    if any(bad in url for bad in bad_domains):
        listing["url"] = ""

    # Skip listings where all 3 key fields are unknown
    unknowns = sum(1 for k in ["location", "pay", "work_model"]
                   if listing.get(k, "Unknown") == "Unknown")
    if unknowns == 3:
        return None

    return listing


def parse_listings(groq_client, raw_text, query):
    """Ask Groq to extract structured job listings from raw search results."""
    if not raw_text.strip():
        return []

    prompt = f"""You are a strict job data extraction agent. Extract ONLY real, specific 2027 summer internship listings from the search results below.

STRICT RULES:
- Only include roles explicitly labeled "Summer 2027" or "2027" — exclude anything else
- Only include undergraduate-eligible roles (not PhD-only)
- Only data analyst, data scientist, analytics, or BI roles — not pure software engineering
- For "url": use ONLY the exact URL from the search result that links directly to the job posting. If no direct job URL exists, use "" (empty string) — never invent or guess a URL
- For "pay": use ONLY pay explicitly mentioned. If not mentioned, use "Unknown"
- For "location": use ONLY location explicitly mentioned. If not mentioned, use "Unknown"
- For "work_model": Onsite / Remote / Hybrid only if explicitly stated, else "Unknown"
- If fewer than 2 fields are known for a listing, skip it entirely

Return ONLY a JSON array. Each object must have exactly these keys:
- role, company, location, work_model, type, pay, status, notes, url

If no qualifying roles found, return: []
Return ONLY the JSON array, no markdown, no explanation.

Search results:
{raw_text[:3000]}"""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1500,
        )
        text = response.choices[0].message.content.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1:
            return []
        return json.loads(text[start:end+1])
    except Exception as e:
        print(f"  Groq parse error: {e}")
        return []


def assess_fit(groq_client, role, company, notes):
    """Ask Groq to assess fit for Tiffany's resume."""
    tiffany_profile = """
Tiffany Sun — Amherst College junior, Math & CS major, GPA 3.60, graduating May 2028.
Skills: Python, R, SQL, Java, Git, Excel, Tableau/Plotly, Shiny, Pandas, NumPy, Seaborn.
Experience: Statistics & Data Science Fellow (logistic regression, data pipelines, Git),
Summer Research Fellow (correlational analysis, survey data).
Projects: Starbucks RFM segmentation (100k transactions), NYC CrashLens (2.27M crash records, R Shiny),
Heart Disease prediction (logistic regression, AIC selection).
Certifications: CodePath AI Engineering, IBM Data Analytics.
NOT a fit for: quant finance (HFT, hedge funds), PhD-level ML, pure software engineering.
"""
    prompt = f"""Given this candidate profile:
{tiffany_profile}

Rate this internship:
Role: {role}
Company: {company}
Notes: {notes}

Reply with ONLY a JSON object with exactly these keys:
- fit: one of "Strong Fit" / "Decent Fit" / "Reach" / "Not a Fit Yet"
- priority: one of "1 - Apply Now" / "2 - Worth Applying" / "3 - Stretch" / "4 - Not Yet"
- reason: one sentence explaining why

Return ONLY the JSON object."""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
        )
        text = response.choices[0].message.content.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"  Fit assessment error: {e}")
        return {"fit": "Unknown", "priority": "Unknown", "reason": "Could not assess"}


# ── MAIN ─────────────────────────────────────────────────────────────────────

def run():
    print(f"\n{'='*55}")
    print(f"  Internship Agent — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}\n")

    tavily = TavilyClient(api_key=TAVILY_API_KEY)
    groq_client = Groq(api_key=GROQ_API_KEY)

    seen_keys, existing_rows = load_existing(CSV_PATH)
    print(f"Loaded {len(existing_rows)} existing listings from CSV.\n")

    all_new_listings = []

    for i, query in enumerate(SEARCH_QUERIES, 1):
        print(f"[{i}/{len(SEARCH_QUERIES)}] Searching: {query[:60]}...")

        raw = search_web(tavily, query)
        listings = parse_listings(groq_client, raw, query)
        print(f"  → Found {len(listings)} listings in search results")

        for listing in listings:
            # Clean and validate
            listing = clean_listing(listing)
            if not listing:
                continue

            role    = listing.get("role", "").strip()
            company = listing.get("company", "").strip()
            if not role or not company:
                continue

            key = (role.lower(), company.lower())
            if key in seen_keys:
                continue

            print(f"  ✦ NEW: {role} at {company}")

            # Find direct apply URL if we don't have a good one
            apply_url = listing.get("url", "")
            if not apply_url:
                print(f"    → Finding direct apply link...")
                apply_url = find_apply_url(tavily, role, company)

            # Assess fit
            fit_data = assess_fit(groq_client, role, company, listing.get("notes", ""))

            new_row = {
                "Role":               role,
                "Company":            company,
                "Location":           listing.get("location", "Unknown"),
                "Work Model":         listing.get("work_model", "Unknown"),
                "Type":               listing.get("type", "Data Analytics"),
                "Pay (est.)":         listing.get("pay", "Unknown"),
                "Application Status": listing.get("status", "Unknown"),
                "Tiffany's Fit":      fit_data.get("fit", "Unknown"),
                "Priority":           fit_data.get("priority", "Unknown"),
                "Fit Reason":         fit_data.get("reason", ""),
                "Notes":              listing.get("notes", ""),
                "Apply URL":          apply_url,
                "Date Found":         datetime.now().strftime("%Y-%m-%d"),
            }

            all_new_listings.append(new_row)
            seen_keys.add(key)

        time.sleep(1)

    if all_new_listings:
        for row in existing_rows:
            if "Date Found" not in row:
                row["Date Found"] = "pre-agent"
        all_rows = existing_rows + all_new_listings
        save_csv(CSV_PATH, all_rows)
        print(f"\n✅ Added {len(all_new_listings)} new listings to {CSV_PATH}")
    else:
        print(f"\n✅ No new listings found this week. CSV unchanged.")

    print(f"\nDone. Next run scheduled for next week.\n")


if __name__ == "__main__":
    run()
