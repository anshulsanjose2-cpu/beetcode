#!/usr/bin/env python3
"""
generate_hints.py — Batch-generate hints + answers for all problems in Turso
                    using a local Ollama LLM.

Usage:
    # Make sure Ollama is running and the model is pulled:
    #   ollama pull qwen2.5-coder:7b
    #
    python generate_hints.py

    # Override model or limit to N problems:
    python generate_hints.py --model qwen2.5-coder:7b --limit 50

    # Re-generate hints/answers for problems that already have one:
    python generate_hints.py --overwrite

Environment variables (or set in .env):
    TURSO_DATABASE_URL   — e.g. https://your-db.turso.io
    TURSO_AUTH_TOKEN     — Turso auth token
    OLLAMA_HOST          — default http://localhost:11434
"""

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ── Load .env if present ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional

from db import TursoDB


OLLAMA_HOST   = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = "qwen2.5-coder:7b"

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

Hint (no code, 2-4 sentences):"""

ANSWER_PROMPT = """\
You are an expert software engineer. Solve the following LeetCode problem in Python.
Write clean, well-commented Python code with:
- A class Solution with the appropriate method
- Time and space complexity noted in a comment at the top
- Brief inline comments explaining key steps

Problem: {title}
Difficulty: {difficulty}
Topics: {topics}

Python solution:"""


def check_ollama(host: str, model: str) -> bool:
    try:
        r = requests.get(f"{host}/api/tags", timeout=5)
        if not r.ok:
            return False
        models = [m["name"] for m in r.json().get("models", [])]
        if model not in models:
            base = model.split(":")[0]
            if not any(m.startswith(base) for m in models):
                print(f"[warn] Model '{model}' not found. Available: {models}")
                print(f"       Run: ollama pull {model}")
                return False
        return True
    except Exception as e:
        print(f"[error] Cannot reach Ollama at {host}: {e}")
        return False


def _call(host: str, model: str, prompt: str, max_tokens: int) -> str:
    payload = {
        "model":  model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": max_tokens},
    }
    r = requests.post(f"{host}/api/generate", json=payload, timeout=180)
    r.raise_for_status()
    return r.json().get("response", "").strip()


def generate_hint(host: str, model: str, title: str, difficulty: str,
                  topics: list[str]) -> str:
    prompt = HINT_PROMPT.format(
        title=title, difficulty=difficulty,
        topics=", ".join(topics) if topics else "General",
    )
    return _call(host, model, prompt, max_tokens=200)


def generate_answer(host: str, model: str, title: str, difficulty: str,
                    topics: list[str]) -> str:
    prompt = ANSWER_PROMPT.format(
        title=title, difficulty=difficulty,
        topics=", ".join(topics) if topics else "General",
    )
    raw = _call(host, model, prompt, max_tokens=600)
    # Strip markdown code fences if model wraps output
    if raw.startswith("```"):
        lines = raw.splitlines()
        inner = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(inner).strip()
    return raw


def main():
    parser = argparse.ArgumentParser(description="Generate hints + answers for Beetcode problems")
    parser.add_argument("--model",     default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--limit",     type=int, default=0,   help="Max problems to process (0 = all)")
    parser.add_argument("--overwrite", action="store_true",   help="Re-generate even if hint exists")
    parser.add_argument("--workers",   type=int, default=4,   help="Parallel threads (default 4)")
    args = parser.parse_args()

    turso_url   = os.getenv("TURSO_DATABASE_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN",   "")
    if not turso_url or not turso_token:
        sys.exit("[error] Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN env vars.")

    print(f"Connecting to Turso at {turso_url[:40]}…")
    db = TursoDB(turso_url, turso_token)
    db.init_schema()  # ensure hints table + answer column exist

    if args.overwrite:
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
        print("All problems already have hints/answers. Use --overwrite to regenerate.")
        return

    print(f"Found {total} problem(s) to process.")

    if not check_ollama(OLLAMA_HOST, args.model):
        sys.exit(1)

    print(f"Using model: {args.model}  |  Ollama: {OLLAMA_HOST}  |  Workers: {args.workers}\n")

    import threading
    print_lock = threading.Lock()

    def process(i: int, prob: dict) -> bool:
        pid    = prob["id"]
        title  = prob["title"]
        diff   = prob["difficulty"]
        topics = prob["topics"]
        t0 = time.time()
        try:
            hint   = generate_hint(OLLAMA_HOST, args.model, title, diff, topics)
            answer = generate_answer(OLLAMA_HOST, args.model, title, diff, topics)
            db.save_hint(pid, hint, answer)
            elapsed = time.time() - t0
            with print_lock:
                print(f"[{i}/{total}] ✓ {title} ({diff}) — {elapsed:.1f}s")
            return True
        except Exception as e:
            with print_lock:
                print(f"[{i}/{total}] ✗ {title} — {e}")
            return False

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process, i, prob): prob
                   for i, prob in enumerate(problems, 1)}
        for fut in as_completed(futures):
            if fut.result():
                ok += 1
            else:
                fail += 1

    print(f"\nFinished: {ok} succeeded, {fail} failed out of {total} problems.")


if __name__ == "__main__":
    main()
