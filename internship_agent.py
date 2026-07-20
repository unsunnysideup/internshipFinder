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
# Loads keys from .env file in the same folder as this script
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

if not GROQ_API_KEY or not TAVILY_API_KEY:
    raise EnvironmentError(
        "Missing API keys. Make sure your .env file exists and contains "
        "GROQ_API_KEY and TAVILY_API_KEY."
    )

CSV_PATH = os.path.expanduser("~/internships/2027_summer_data_internships.csv")

SEARCH_QUERIES = [
    "2027 summer data analyst intern undergraduate apply now",
    "2027 summer data scientist intern undergraduate open application",
    "2027 summer business intelligence intern undergraduate",
    "2027 summer analytics intern undergraduate new posting",
    "site:linkedin.com 2027 summer data analyst intern undergraduate",
    "site:greenhouse.io OR site:lever.co 2027 summer data analyst intern",
    "2027 summer data science intern FAANG tech undergraduate",
    "2027 summer data intern finance undergraduate new york",
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
    """Run one Tavily search and return raw results text."""
    try:
        result = tavily.search(
            query=query,
            search_depth="basic",
            max_results=8,
            include_answer=True
        )
        snippets = []
        for r in result.get("results", []):
            snippets.append(f"Title: {r.get('title','')}\nURL: {r.get('url','')}\nSnippet: {r.get('content','')}\n")
        return "\n---\n".join(snippets)
    except Exception as e:
        print(f"  Tavily error for '{query}': {e}")
        return ""


def parse_listings(groq_client, raw_text, query):
    """Ask Groq to extract structured job listings from raw search results."""
    if not raw_text.strip():
        return []

    prompt = f"""You are a job data extraction agent. Below are web search results for: "{query}"

Extract every 2027 summer internship listing for undergraduate data analyst, data scientist, or analytics roles in the US.

Return ONLY a JSON array. Each object must have exactly these keys:
- role: exact job title
- company: company name
- location: city/state or Remote or Hybrid
- work_model: Onsite / Remote / Hybrid / Unknown
- type: Data Analyst / Data Scientist / Data Analytics / Business Intelligence / Quant
- pay: pay rate if mentioned, else Unknown
- status: Open / Closed / Unknown
- notes: one sentence max about the role
- url: direct application URL if available, else company careers page

Only include roles that are:
1. For summer 2027 (not 2026 or earlier)
2. For undergraduates (not PhD-only)
3. In data analyst, data scientist, analytics, or BI — not pure software engineering

If no qualifying roles found, return an empty array: []
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
        # Strip markdown fences if present
        text = text.replace("```json", "").replace("```", "").strip()
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1:
            return []
        return json.loads(text[start:end+1])
    except Exception as e:
        print(f"  Groq parse error: {e}")
        return []


def assess_fit(groq_client, role, company, notes):
    """Ask Groq to assess fit for Tiffany's resume quickly."""
    tiffany_profile = """
Tiffany Sun — Amherst College junior, Math & CS major, GPA 3.60, graduating May 2028.
Skills: Python, R, SQL, Java, Git, Excel, Tableau/Plotly, Shiny, Pandas, NumPy, Seaborn.
Experience: Statistics & Data Science Fellow (logistic regression, data pipelines, Git),
Summer Research Fellow (correlational analysis, survey data), 
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

    # Load existing listings
    seen_keys, existing_rows = load_existing(CSV_PATH)
    print(f"Loaded {len(existing_rows)} existing listings from CSV.\n")

    all_new_listings = []

    for i, query in enumerate(SEARCH_QUERIES, 1):
        print(f"[{i}/{len(SEARCH_QUERIES)}] Searching: {query[:60]}...")

        raw = search_web(tavily, query)
        listings = parse_listings(groq_client, raw, query)
        print(f"  → Found {len(listings)} listings in search results")

        for listing in listings:
            role    = listing.get("role", "").strip()
            company = listing.get("company", "").strip()
            if not role or not company:
                continue

            key = (role.lower(), company.lower())
            if key in seen_keys:
                continue  # Already in CSV

            # New listing — assess fit
            print(f"  ✦ NEW: {role} at {company}")
            fit_data = assess_fit(groq_client, role, company, listing.get("notes", ""))

            new_row = {
                "Role":              role,
                "Company":           company,
                "Location":          listing.get("location", "Unknown"),
                "Work Model":        listing.get("work_model", "Unknown"),
                "Type":              listing.get("type", "Data Analytics"),
                "Pay (est.)":        listing.get("pay", "Unknown"),
                "Application Status": listing.get("status", "Unknown"),
                "Tiffany's Fit":     fit_data.get("fit", "Unknown"),
                "Priority":          fit_data.get("priority", "Unknown"),
                "Fit Reason":        fit_data.get("reason", ""),
                "Notes":             listing.get("notes", ""),
                "Apply URL":         listing.get("url", ""),
                "Date Found":        datetime.now().strftime("%Y-%m-%d"),
            }

            all_new_listings.append(new_row)
            seen_keys.add(key)

        time.sleep(1)  # Be polite to APIs

    # Save results
    if all_new_listings:
        # Add Date Found column to existing rows if missing
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