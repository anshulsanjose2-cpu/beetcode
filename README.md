# Beetcode

A LeetCode-style dark-themed web app for browsing company-wise interview questions — filtered by company, timeframe, difficulty, and topic.

> Live app → [beetcode.streamlit.app](https://beetcode.streamlit.app) *(replace with your Streamlit Cloud URL)*

![screenshot](https://via.placeholder.com/900x500/1a1a1a/ffa116?text=Beetcode+Screenshot)

---

## Features

- **665+ companies** with questions sourced from real interview reports
- **5 timeframes** — All Time, Last 30 Days, Last 3 Months, Last 6 Months, More than 6 Months
- **Topic tags** fetched from LeetCode's API (Array, DP, Graph, Tree, …)
- **Filters** — company, timeframe, difficulty (Easy / Medium / Hard), topic, title search
- **Dark theme** replicating LeetCode's UI — colour-coded difficulty badges and topic chips
- **Turso (libSQL) backend** — normalized relational schema, all queries served from the cloud DB

---

## Project structure

```
beetcode/
├── leetcode_app.py   # Streamlit UI — filters, table, stats bar
├── db.py             # TursoDB class — schema, all SQL queries
├── seed.py           # One-time data ingestion (local only)
├── requirements.txt
├── .streamlit/
│   ├── config.toml   # Dark theme
│   └── secrets.toml  # Turso credentials (git-ignored)
└── .gitignore
```

---

## Database schema

```
problems        id, slug, title, difficulty, url
topics          id, name
problem_topics  problem_id ↔ topic_id   (many-to-many)
companies       id, name
company_problems company_id, problem_id, timeframe, acceptance_pct, frequency_pct
```

All five timeframe CSVs per company are normalised into a single `company_problems` table with a `timeframe` column — problems are stored once and referenced everywhere.

---

## Local setup

### 1. Clone and install

```bash
git clone https://github.com/anshulsanjose2-cpu/beetcode.git
cd beetcode
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Add Turso credentials

Create `.streamlit/secrets.toml` (git-ignored):

```toml
TURSO_DATABASE_URL = "https://<db-name>-<org>.turso.io"
TURSO_AUTH_TOKEN   = "<your-auth-token>"
```

Get these from [app.turso.tech](https://app.turso.tech) → your database → **Connect**.

### 3. Seed the database (first time only)

Place the company CSV data in:

```
leetcode-companywise-interview-questions-master/
├── amazon/
│   ├── all.csv
│   ├── six-months.csv
│   ├── three-months.csv
│   ├── thirty-days.csv
│   └── more-than-six-months.csv
├── google/
│   └── ...
└── ...
```

Then run:

```bash
python seed.py
```

This will:
1. Scan all company folders in parallel (12 workers)
2. Insert companies, problems, and topics into Turso
3. Fetch topic tags from LeetCode's GraphQL API (3 workers)
4. Insert all company-problem records in transactional batches

Takes ~3–5 minutes on first run. Only needs to run once — or again if the source data changes.

### 4. Run the app

```bash
streamlit run leetcode_app.py
```

Open [http://localhost:8501](http://localhost:8501).

---

## Refreshing data

The deployed app is **read-only** against Turso. To refresh:

```bash
python seed.py --reset     # drops all tables, re-seeds from scratch
```

The deployed app picks up changes immediately — no redeploy needed.

---

## Deployment (Streamlit Community Cloud)

1. Push code to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**
3. Select repo `anshulsanjose2-cpu/beetcode`, branch `main`, file `leetcode_app.py`
4. Under **Advanced settings → Secrets**, add:

```toml
TURSO_DATABASE_URL = "https://..."
TURSO_AUTH_TOKEN   = "..."
```

5. Click **Deploy**

The CSV data is never deployed — only the app code is. All data is served from Turso.

---

## Tech stack

| Layer | Tech |
|---|---|
| UI | [Streamlit](https://streamlit.io) |
| Database | [Turso](https://turso.tech) (libSQL / distributed SQLite) |
| Data source | LeetCode company-wise interview questions + LeetCode GraphQL API |
| Language | Python 3.10+ |
