#!/usr/bin/env python3
"""
generate_hints.py — Batch-generate hints for all problems in Turso using a local Ollama LLM.

Usage:
    # Make sure Ollama is running and the model is pulled:
    #   ollama pull deepseek-coder:6.7b
    #
    python generate_hints.py

    # Override model or limit to N problems:
    python generate_hints.py --model deepseek-coder:6.7b --limit 50

    # Re-generate hints for problems that already have one:
    python generate_hints.py --overwrite

Environment variables (or set in .env):
    TURSO_DATABASE_URL   — e.g. libsql://your-db.turso.io
    TURSO_AUTH_TOKEN     — Turso auth token
    OLLAMA_HOST          — default http://localhost:11434
"""

import argparse
import os
import sys
import time

import requests

# ── Load .env if present ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional

from db import TursoDB


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = "deepseek-coder:6.7b"

HINT_PROMPT = """\
You are a coding interview coach. Given a LeetCode problem, provide a concise hint \
(2-4 sentences) that guides the candidate toward the right approach WITHOUT giving \
away the full solution or any code. Focus on:
- Which data structure or algorithm pattern fits best
- The key insight or observation needed
- The time/space complexity to aim for

Problem: {title}
Difficulty: {difficulty}
Topics: {topics}

Hint:"""


def check_ollama(host: str, model: str) -> bool:
    """Return True if Ollama is reachable and the model is available."""
    try:
        r = requests.get(f"{host}/api/tags", timeout=5)
        if not r.ok:
            return False
        models = [m["name"] for m in r.json().get("models", [])]
        if model not in models:
            # Try prefix match (e.g. "deepseek-coder" matches "deepseek-coder:6.7b")
            base = model.split(":")[0]
            if not any(m.startswith(base) for m in models):
                print(f"[warn] Model '{model}' not found. Available: {models}")
                print(f"       Run: ollama pull {model}")
                return False
        return True
    except Exception as e:
        print(f"[error] Cannot reach Ollama at {host}: {e}")
        return False


def generate_hint(host: str, model: str, title: str, difficulty: str,
                  topics: list[str]) -> str:
    prompt = HINT_PROMPT.format(
        title=title,
        difficulty=difficulty,
        topics=", ".join(topics) if topics else "General",
    )
    payload = {
        "model":  model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 200,
        },
    }
    r = requests.post(f"{host}/api/generate", json=payload, timeout=120)
    r.raise_for_status()
    return r.json().get("response", "").strip()


def main():
    parser = argparse.ArgumentParser(description="Generate hints for Beetcode problems")
    parser.add_argument("--model",     default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--limit",     type=int, default=0,   help="Max problems to process (0 = all)")
    parser.add_argument("--overwrite", action="store_true",   help="Re-generate even if hint exists")
    args = parser.parse_args()

    turso_url   = os.getenv("TURSO_DATABASE_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN",   "")
    if not turso_url or not turso_token:
        sys.exit("[error] Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN env vars.")

    print(f"Connecting to Turso at {turso_url[:40]}…")
    db = TursoDB(turso_url, turso_token)
    db.init_schema()  # ensure hints table exists

    if args.overwrite:
        # fetch all problems
        all_rows = db.rows("""
            SELECT p.id, p.title, p.difficulty,
                   GROUP_CONCAT(DISTINCT t.name) AS topics
            FROM problems p
            LEFT JOIN problem_topics pt ON pt.problem_id = p.id
            LEFT JOIN topics t ON t.id = pt.topic_id
            GROUP BY p.id ORDER BY p.id
        """)
        problems = [
            {
                "id":         db._val(r[0]),
                "title":      db._val(r[1]) or "",
                "difficulty": db._val(r[2]) or "",
                "topics":     [x for x in (db._val(r[3]) or "").split(",") if x],
            }
            for r in all_rows
        ]
    else:
        problems = db.get_problems_without_hints()

    if args.limit:
        problems = problems[: args.limit]

    total = len(problems)
    if total == 0:
        print("All problems already have hints. Use --overwrite to regenerate.")
        return

    print(f"Found {total} problem(s) to process.")

    if not check_ollama(OLLAMA_HOST, args.model):
        sys.exit(1)

    print(f"Using model: {args.model}  |  Ollama: {OLLAMA_HOST}\n")

    ok = fail = 0
    for i, prob in enumerate(problems, 1):
        pid    = prob["id"]
        title  = prob["title"]
        diff   = prob["difficulty"]
        topics = prob["topics"]

        print(f"[{i}/{total}] {title} ({diff}) … ", end="", flush=True)
        t0 = time.time()
        try:
            hint = generate_hint(OLLAMA_HOST, args.model, title, diff, topics)
            db.save_hint(pid, hint)
            elapsed = time.time() - t0
            print(f"done ({elapsed:.1f}s)")
            ok += 1
        except Exception as e:
            print(f"FAILED — {e}")
            fail += 1

    print(f"\nFinished: {ok} succeeded, {fail} failed out of {total} problems.")


if __name__ == "__main__":
    main()
