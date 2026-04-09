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

## Features

- **665+ companies** with questions sourced from real interview reports
- **5 timeframes** — All Time, Last 30 Days, Last 3 Months, Last 6 Months, More than 6 Months
- **Topic tags** fetched from LeetCode's API (Array, DP, Graph, Tree, …)
- **Filters** — company, timeframe, difficulty (Easy / Medium / Hard), topic, title search
- **Dark theme** replicating LeetCode's UI — colour-coded difficulty badges and topic chips
- **Built-in code editor** with syntax highlighting (Ace editor)
- **Sandboxed test runner** — execute Python solutions safely in an isolated subprocess
- **LLM hints and answers** — generated locally via Ollama, stored in Turso
- **Turso (libSQL) backend** — normalized relational schema, all queries served from the cloud DB

---

## Project structure

```
beetcode/
├── leetcode_app.py    # Streamlit UI — filters, table, code editor, hints dialog
├── db.py              # TursoDB class — schema, all SQL queries
├── seed.py            # One-time data ingestion from CSVs + LeetCode API
├── check_missing.py   # Compare LeetCode full list vs DB, insert missing problems, fix topic tags
├── generate_hints.py  # Batch LLM hint/answer generation via Ollama
├── leetcode_api.py    # Fetches live problem descriptions from LeetCode GraphQL
├── executor.py        # Sandboxed Python code runner for test cases
├── requirements.txt
├── .streamlit/
│   ├── config.toml    # Dark theme
│   └── secrets.toml   # Turso credentials (git-ignored)
└── .gitignore
```

---

## Database schema

```
problems         id, slug, title, difficulty, url
topics           id, name
problem_topics   problem_id ↔ topic_id   (many-to-many)
companies        id, name
company_problems company_id, problem_id, timeframe, acceptance_pct, frequency_pct
users            id, username
user_problems    user_id, problem_id  (solved tracking)
user_solutions   user_id, problem_id, code
hints            problem_id, hint, answer
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

## Generating hints and answers (`generate_hints.py`)

Uses a local [Ollama](https://ollama.com) model to generate hints and Python solutions for all problems and stores them in Turso.

### Providers

| Provider | Flag | Rate limit | Model |
|----------|------|-----------|-------|
| Ollama (local) | `--provider ollama` | No limit | `qwen2.5-coder:7b` |
| Groq | `--provider groq` | 20 RPM (free) | `llama-3.3-70b-versatile` |
| Cerebras | `--provider cerebras` | 20 RPM (free) | `llama3.1-8b` (fastest) or `qwen-3-235b-a22b-instruct-2507` (best quality) |

**Ollama (local, default)**
```bash
ollama pull qwen2.5-coder:7b
python generate_hints.py
```

**Groq (cloud, fast)**
```bash
export GROQ_API_KEY="your-key"       # from console.groq.com
python generate_hints.py --provider groq
```

**Cerebras (cloud, fastest — ~2000 tokens/s)**
```bash
export CEREBRAS_API_KEY="your-key"   # from cloud.cerebras.ai
python generate_hints.py --provider cerebras
```

### Usage

```bash
# Generate hints + answers for all problems that have neither
python generate_hints.py

# Resume after a crash — only generate missing answers (preserves existing hints)
python generate_hints.py --answers-only --provider groq

# Generate hint + answer for a single problem by ID
python generate_hints.py -p 14

# Generate only the answer for a single problem (hint already exists)
python generate_hints.py -p 14 --answers-only

# Re-generate everything from scratch
python generate_hints.py --overwrite

# Limit to 50 problems, use more workers
python generate_hints.py --limit 50 --workers 8
```

### All flags

| Flag | Description |
|------|-------------|
| `--provider` | `ollama` (default), `groq`, or `cerebras` |
| `--model MODEL` | Model override |
| `--limit N` | Process at most N problems |
| `--workers N` | Parallel threads (default: 4) |
| `--overwrite` | Re-generate hint + answer even if they already exist |
| `--missing-answer` | Only process problems that are missing an answer |
| `--answers-only` | Only generate answers, skip hint generation |
| `-p, --problem-id ID` | Process a single problem by its numeric ID |

---

## Code execution sandbox (`executor.py`)

User-submitted Python code runs in an isolated subprocess with:

- **5-second CPU timeout** — solutions that loop forever are killed
- **256 MB memory cap**
- **Blocked network modules** — `socket`, `urllib`, `http`, etc.
- **Blocked builtins** — `open`, `input`, `compile`, `breakpoint`
- **Secrets stripped** — `TURSO_AUTH_TOKEN` and `TURSO_DATABASE_URL` are removed from the subprocess environment

Test cases use the format `functionCall(args) → expected`, e.g.:

```
Solution().twoSum([2,7,11,15], 9) → [0, 1]
```

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
| UI | [Streamlit](https://streamlit.io) + Ace editor |
| Database | [Turso](https://turso.tech) (libSQL / distributed SQLite) |
| LLM | [Ollama](https://ollama.com) (`qwen2.5-coder:7b` default) |
| Data source | LeetCode company-wise CSV data + LeetCode GraphQL API |
| Code runner | Python `subprocess` with resource limits |
| Language | Python 3.10+ |
