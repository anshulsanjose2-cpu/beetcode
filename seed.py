"""
One-time database seeder.

Usage:
    python seed.py           # seed from scratch
    python seed.py --reset   # drop all tables then re-seed
"""

import math
import sys
import time
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from db import TursoDB

DATA_ROOT = Path("leetcode-companywise-interview-questions-master")

TIMEFRAME_FILES = {
    "all":                  "all.csv",
    "six-months":           "six-months.csv",
    "three-months":         "three-months.csv",
    "thirty-days":          "thirty-days.csv",
    "more-than-six-months": "more-than-six-months.csv",
}

GRAPHQL_URL   = "https://leetcode.com/graphql"
GRAPHQL_QUERY = """
query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
  problemsetQuestionList: questionList(
    categorySlug: $categorySlug limit: $limit skip: $skip filters: $filters
  ) {
    total: totalNum
    questions: data {
      frontendQuestionId: questionFrontendId
      titleSlug
      topicTags { name }
    }
  }
}
"""

# ── Step 1: scan all CSV files in parallel ────────────────────────────────────

def _read_company(company_dir: Path):
    company = company_dir.name
    probs: dict[int, dict] = {}
    rows:  list[tuple]     = []

    for tf_key, csv_name in TIMEFRAME_FILES.items():
        csv_path = company_dir / csv_name
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(csv_path)
            df.columns = [c.strip() for c in df.columns]
            for _, row in df.iterrows():
                pid = row.get("ID")
                if pd.isna(pid):
                    continue
                pid = int(pid)
                url  = str(row.get("URL", "")).strip()
                slug = url.rstrip("/").split("/")[-1]

                def _pct(col):
                    try:
                        v = float(str(row.get(col, 0)).replace("%", "").strip())
                        return 0.0 if (math.isnan(v) or math.isinf(v)) else v
                    except Exception:
                        return 0.0

                if pid not in probs:
                    probs[pid] = {
                        "id":         pid,
                        "slug":       slug,
                        "title":      str(row.get("Title", "")).strip(),
                        "difficulty": str(row.get("Difficulty", "")).strip(),
                        "url":        url,
                    }
                rows.append((company, pid, tf_key, _pct("Acceptance %"), _pct("Frequency %")))
        except Exception as exc:
            print(f"  ⚠ {csv_path}: {exc}")

    return company, probs, rows


def scan_csvs() -> tuple[set, dict, list]:
    company_dirs = sorted(d for d in DATA_ROOT.iterdir()
                          if d.is_dir() and not d.name.startswith("."))
    print(f"Scanning {len(company_dirs)} company folders (parallel) …")

    companies: set[str]        = set()
    problems:  dict[int, dict] = {}
    cp_rows:   list[tuple]     = []
    done = 0

    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(_read_company, d): d for d in company_dirs}
        for f in as_completed(futures):
            company, probs, rows = f.result()
            companies.add(company)
            for pid, p in probs.items():
                if pid not in problems:
                    problems[pid] = p
            cp_rows.extend(rows)
            done += 1
            print(f"  {done}/{len(company_dirs)}", end="\r", flush=True)

    print(f"\n  {len(companies)} companies · {len(problems):,} problems · "
          f"{len(cp_rows):,} company-problem records")
    return companies, problems, cp_rows


# ── Step 2: fetch topic tags from LeetCode (parallel pages) ───────────────────

def fetch_lc_tags() -> dict[str, list[str]]:
    tags: dict[str, list[str]] = {}
    headers = {"Content-Type": "application/json",
               "Referer":      "https://leetcode.com/problemset/"}

    def post(skip, limit=100):
        return requests.post(
            GRAPHQL_URL,
            json={"query": GRAPHQL_QUERY,
                  "variables": {"categorySlug": "", "skip": skip,
                                "limit": limit, "filters": {}}},
            headers=headers, timeout=15,
        ).json()

    try:
        total = post(0, 1)["data"]["problemsetQuestionList"]["total"]
    except Exception as exc:
        print(f"  ⚠ Cannot reach LeetCode API: {exc}")
        return tags

    print(f"Fetching tags for {total:,} problems (3 workers) …")
    skips   = list(range(0, total, 100))
    fetched = 0

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(post, s): s for s in skips}
        for f in as_completed(futures):
            try:
                for q in f.result()["data"]["problemsetQuestionList"]["questions"]:
                    tags[q["titleSlug"]] = [t["name"] for t in q["topicTags"]]
            except Exception:
                pass
            fetched += 100
            print(f"  {min(fetched, total):,}/{total:,}", end="\r", flush=True)

    print(f"\n  Tags fetched for {len(tags):,} problems")
    return tags


# ── Main seeder ───────────────────────────────────────────────────────────────

def seed(db: TursoDB, *, progress_cb=None) -> None:
    """
    Full seeding pipeline.
    progress_cb(step: str, pct: float) is called at each stage (optional).
    """
    def _cb(step, pct):
        if progress_cb:
            progress_cb(step, pct)
        else:
            print(f"[{pct:3.0%}] {step}")

    # 1. Scan CSVs
    _cb("Reading CSV files …", 0.0)
    companies, problems, cp_rows = scan_csvs()

    # 2. Companies
    _cb("Inserting companies …", 0.02)
    db.batch([db._stmt("INSERT OR IGNORE INTO companies (name) VALUES (?)", [c])
              for c in companies])
    company_id = {db._val(r[1]): db._val(r[0])
                  for r in db.rows("SELECT id, name FROM companies")}

    # 3. Problems
    _cb(f"Inserting {len(problems):,} problems …", 0.05)
    db.batch([db._stmt(
        "INSERT OR REPLACE INTO problems (id,slug,title,difficulty,url) VALUES(?,?,?,?,?)",
        [p["id"], p["slug"], p["title"], p["difficulty"], p["url"]])
        for p in problems.values()])
    slug_to_id = {p["slug"]: p["id"] for p in problems.values()}

    # 4. LeetCode topic tags
    _cb("Fetching topic tags from LeetCode …", 0.15)
    lc_tags = fetch_lc_tags()

    # 5. Topics
    all_topic_names = {tag for tags in lc_tags.values() for tag in tags}
    _cb(f"Inserting {len(all_topic_names)} topics …", 0.52)
    db.batch([db._stmt("INSERT OR IGNORE INTO topics (name) VALUES (?)", [t])
              for t in all_topic_names])
    topic_id = {db._val(r[1]): db._val(r[0])
                for r in db.rows("SELECT id, name FROM topics")}

    # 6. Problem-topics
    pt_pairs = [(slug_to_id[slug], topic_id[tag])
                for slug, tags in lc_tags.items()
                if slug in slug_to_id
                for tag in tags if tag in topic_id]
    _cb(f"Inserting {len(pt_pairs):,} problem-topic links …", 0.56)
    db.batch([db._stmt("INSERT OR IGNORE INTO problem_topics (problem_id,topic_id) VALUES(?,?)",
                       [pid, tid]) for pid, tid in pt_pairs])

    # 7. Company-problems (largest table — show per-chunk progress)
    valid_pids = set(problems.keys())
    cp_stmts = [
        db._stmt(
            "INSERT OR REPLACE INTO company_problems "
            "(company_id,problem_id,timeframe,acceptance_pct,frequency_pct) VALUES(?,?,?,?,?)",
            [company_id[co], pid, tf, acc, freq],
        )
        for co, pid, tf, acc, freq in cp_rows
        if co in company_id and pid in valid_pids
    ]
    total_cp = len(cp_stmts)
    CHUNK = 500
    for i in range(0, total_cp, CHUNK):
        db.batch(cp_stmts[i : i + CHUNK])
        pct = 0.6 + 0.4 * min((i + CHUNK) / total_cp, 1.0)
        _cb(f"Company-problems: {min(i+CHUNK, total_cp):,}/{total_cp:,}", pct)

    _cb("Done!", 1.0)


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tomllib
    secrets = tomllib.loads(Path(".streamlit/secrets.toml").read_text())
    reset = "--reset" in sys.argv
    db = TursoDB(url=secrets["TURSO_DATABASE_URL"], token=secrets["TURSO_AUTH_TOKEN"])

    if reset:
        print("Dropping all tables …")
        db.drop_all()

    print("Initialising schema …")
    db.init_schema()

    t0 = time.time()
    seed(db)
    elapsed = time.time() - t0

    print(f"\nSeeding complete in {elapsed:.0f}s. Row counts:")
    for table, count in db.stats().items():
        print(f"  {table:<22} {count:>8,}")
