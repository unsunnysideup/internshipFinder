# Internship Agent — Setup Guide (Mac)

Runs weekly, searches for new 2027 summer data internships, and appends only new listings to your CSV — automatically scored for your fit.

---

## What you need first

Two free API keys:

1. **Groq** → https://console.groq.com → Sign up → API Keys → Create key
2. **Tavily** → https://app.tavily.com → Sign up → copy your API key

---

## Step 1 — Install Python dependencies

Open Terminal and run:

```bash
pip3 install groq tavily-python
```

---

## Step 2 — Add your API keys

Open `internship_agent.py` in any text editor and replace these two lines near the top:

```python
GROQ_API_KEY   = "YOUR_GROQ_API_KEY_HERE"
TAVILY_API_KEY = "YOUR_TAVILY_API_KEY_HERE"
```

with your actual keys:

```python
GROQ_API_KEY   = "gsk_abc123..."
TAVILY_API_KEY = "tvly-abc123..."
```

Save the file.

---

## Step 3 — Set up your CSV folder

```bash
mkdir -p ~/internships
```

Then copy your existing CSV into that folder:

```bash
cp /path/to/2027_summer_data_internships.csv ~/internships/
```

Or just run the agent once — it will create a new CSV automatically if none exists.

---

## Step 4 — Test it manually

```bash
python3 /path/to/internship_agent.py
```

You should see it searching, finding listings, and printing NEW ones. Check `~/internships/2027_summer_data_internships.csv` when done.

---

## Step 5 — Schedule it to run every Monday at 9am

Mac uses **cron** to schedule tasks. Run this in Terminal:

```bash
crontab -e
```

This opens a text editor. Add this line at the bottom (replace the path with wherever you saved the script):

```
0 9 * * 1 /usr/bin/python3 /Users/YOUR_USERNAME/internships/internship_agent.py >> /Users/YOUR_USERNAME/internships/agent.log 2>&1
```

To find your username, run `whoami` in Terminal.

Save and exit (press `Escape`, then type `:wq`, then Enter if it opened in vim — or just save normally if it opened in nano).

**That's it.** Every Monday at 9am it will run automatically, search for new listings, and update your CSV. Logs go to `~/internships/agent.log` so you can check what it found.

---

## How it works

```
Every Monday at 9am
        │
        ▼
  Tavily searches 8 queries      ← ~8 credits/week (free tier = 1000/month)
        │
        ▼
  Groq (Llama 3.3 70B) parses    ← free, fast
  raw results into structured data
        │
        ▼
  Deduplicate against existing CSV
        │
        ▼
  Groq assesses fit for your resume
        │
        ▼
  Append only NEW listings to CSV
  with Tiffany's Fit + Priority columns
```

---

## Cost estimate

| Service | Usage/week | Cost |
|---------|-----------|------|
| Tavily  | ~8 credits | Free (1000/month free tier) |
| Groq    | ~10 calls  | Free (generous free tier) |
| **Total** | — | **$0/week** |

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'groq'`**
→ Run `pip3 install groq tavily-python` again

**`AuthenticationError`**
→ Double-check your API keys in the script — no spaces, no quotes missing

**Cron job not running**
→ Make sure Mac hasn't blocked Terminal from running in the background:
System Settings → Privacy & Security → Full Disk Access → add Terminal

**Want to run it more often?**
Change `0 9 * * 1` in crontab to:
- Every day at 9am: `0 9 * * *`
- Every Mon/Thu: `0 9 * * 1,4`
