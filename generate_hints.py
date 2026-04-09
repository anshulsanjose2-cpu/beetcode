#!/usr/bin/env python3
"""
generate_hints.py — Batch-generate hints + answers for all problems in Turso
                    using a local Ollama LLM or Groq cloud API.

Usage:
    # Ollama (local):
    python generate_hints.py
    python generate_hints.py --model qwen2.5-coder:7b --limit 50

    # Groq (cloud, much faster):
    GROQ_API_KEY=<key> python generate_hints.py --provider groq
    GROQ_API_KEY=<key> python generate_hints.py --provider groq --model llama-3.3-70b-versatile

    # Re-generate hints/answers for problems that already have one:
    python generate_hints.py --overwrite

Environment variables (or set in .env):
    TURSO_DATABASE_URL   — e.g. https://your-db.turso.io
    TURSO_AUTH_TOKEN     — Turso auth token
    OLLAMA_HOST          — default http://localhost:11434
    GROQ_API_KEY         — Groq API key (required when --provider groq)
"""

import argparse
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ── Load .env if present ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db import TursoDB


OLLAMA_HOST              = os.getenv("OLLAMA_HOST", "http://localhost:11434")
GROQ_API_URL             = "https://api.groq.com/openai/v1/chat/completions"
CEREBRAS_API_URL         = "https://api.cerebras.ai/v1/chat/completions"  # same as OpenAI format
DEFAULT_OLLAMA_MODEL     = "qwen2.5-coder:7b"
DEFAULT_GROQ_MODEL       = "llama-3.3-70b-versatile"
DEFAULT_CEREBRAS_MODEL   = "llama3.1-8b"  # fastest; use qwen-3-235b-a22b-instruct-2507 for best quality
GROQ_RPM_LIMIT           = 20  # conservative — 3s between requests
CEREBRAS_RPM_LIMIT       = 20  # conservative — 3s between requests


# ── Rate limiter ──────────────────────────────────────────────────────────────

def _make_rate_limiter(rpm: int):
    """Simple minimum-interval limiter — no burst, guaranteed gap between requests."""
    interval  = 60.0 / rpm
    lock      = threading.Lock()
    last_call = [0.0]

    def wait():
        while True:
            with lock:
                now = time.monotonic()
                if now - last_call[0] >= interval:
                    last_call[0] = now
                    return
                sleep_for = interval - (now - last_call[0])
            time.sleep(sleep_for)

    return wait


_groq_wait     = _make_rate_limiter(GROQ_RPM_LIMIT)
_cerebras_wait = _make_rate_limiter(CEREBRAS_RPM_LIMIT)


# ── Prompts ───────────────────────────────────────────────────────────────────

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


# ── Provider: Ollama ──────────────────────────────────────────────────────────

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


def _call_ollama(model: str, prompt: str, max_tokens: int) -> str:
    payload = {
        "model":  model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": max_tokens, "num_ctx": 1024},
    }
    r = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=180)
    r.raise_for_status()
    return r.json().get("response", "").strip()


# ── Provider: Groq ────────────────────────────────────────────────────────────

def _call_groq(api_key: str, model: str, prompt: str, max_tokens: int) -> str:
    _groq_wait()
    r = requests.post(
        GROQ_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "max_tokens": max_tokens, "temperature": 0.2},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


# ── Provider: Cerebras ────────────────────────────────────────────────────────

def _call_cerebras(api_key: str, model: str, prompt: str, max_tokens: int) -> str:
    _cerebras_wait()
    r = requests.post(
        CEREBRAS_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "max_tokens": max_tokens, "temperature": 0.2},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


# ── Unified call ──────────────────────────────────────────────────────────────

def _call(provider: str, model: str, prompt: str, max_tokens: int,
          groq_key: str = "", cerebras_key: str = "") -> str:
    if provider == "groq":
        return _call_groq(groq_key, model, prompt, max_tokens)
    if provider == "cerebras":
        return _call_cerebras(cerebras_key, model, prompt, max_tokens)
    return _call_ollama(model, prompt, max_tokens)


def _strip_fences(raw: str) -> str:
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(l for l in lines if not l.startswith("```")).strip()
    return raw


def generate_hint(provider: str, model: str, title: str, difficulty: str,
                  topics: list[str], groq_key: str = "", cerebras_key: str = "") -> str:
    prompt = HINT_PROMPT.format(
        title=title, difficulty=difficulty,
        topics=", ".join(topics) if topics else "General",
    )
    return _call(provider, model, prompt, 200, groq_key, cerebras_key)


def generate_answer(provider: str, model: str, title: str, difficulty: str,
                    topics: list[str], groq_key: str = "", cerebras_key: str = "") -> str:
    prompt = ANSWER_PROMPT.format(
        title=title, difficulty=difficulty,
        topics=", ".join(topics) if topics else "General",
    )
    return _strip_fences(_call(provider, model, prompt, 350, groq_key, cerebras_key))


# ── Problem fetching ──────────────────────────────────────────────────────────

def fetch_problems(db: TursoDB, args) -> list[dict]:
    if args.problem_id:
        rows = db.rows("""
            SELECT p.id, p.title, p.difficulty,
                   GROUP_CONCAT(DISTINCT t.name) AS topics
            FROM problems p
            LEFT JOIN problem_topics pt ON pt.problem_id = p.id
            LEFT JOIN topics t ON t.id = pt.topic_id
            WHERE p.id = ?
            GROUP BY p.id
        """, [args.problem_id])
    elif args.overwrite:
        rows = db.rows("""
            SELECT p.id, p.title, p.difficulty,
                   GROUP_CONCAT(DISTINCT t.name) AS topics
            FROM problems p
            LEFT JOIN problem_topics pt ON pt.problem_id = p.id
            LEFT JOIN topics t ON t.id = pt.topic_id
            GROUP BY p.id ORDER BY p.id
        """)
    else:
        return (db.get_problems_without_answers()
                if args.answers_only or args.missing_answer
                else db.get_problems_without_hints())

    return [
        {
            "id":         db._val(r[0]),
            "title":      db._val(r[1]) or "",
            "difficulty": db._val(r[2]) or "",
            "topics":     [x for x in (db._val(r[3]) or "").split(",") if x],
        }
        for r in rows
    ]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate hints + answers for Beetcode problems")
    parser.add_argument("--provider",       default="ollama", choices=["ollama", "groq", "cerebras"],
                        help="LLM provider (default: ollama)")
    parser.add_argument("--model",          default="", help="Model override")
    parser.add_argument("--limit",          type=int, default=0,   help="Max problems to process (0 = all)")
    parser.add_argument("--overwrite",      action="store_true",   help="Re-generate even if hint/answer exists")
    parser.add_argument("--missing-answer", action="store_true",   help="Only process problems missing an answer")
    parser.add_argument("--answers-only",   action="store_true",   help="Only generate answers, skip hints")
    parser.add_argument("-p", "--problem-id", type=int, default=0, help="Process a single problem by ID")
    parser.add_argument("--workers",        type=int, default=2,   help="Parallel threads (default 2)")
    args = parser.parse_args()

    model = args.model or {
        "groq":     DEFAULT_GROQ_MODEL,
        "cerebras": DEFAULT_CEREBRAS_MODEL,
        "ollama":   DEFAULT_OLLAMA_MODEL,
    }[args.provider]

    turso_url   = os.getenv("TURSO_DATABASE_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN",   "")
    if not turso_url or not turso_token:
        sys.exit("[error] Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN env vars.")

    groq_key     = os.getenv("GROQ_API_KEY",     "")
    cerebras_key = os.getenv("CEREBRAS_API_KEY", "")
    if args.provider == "groq" and not groq_key:
        sys.exit("[error] Set GROQ_API_KEY env var.")
    if args.provider == "cerebras" and not cerebras_key:
        sys.exit("[error] Set CEREBRAS_API_KEY env var.")

    print(f"Connecting to Turso at {turso_url[:40]}…")
    db = TursoDB(turso_url, turso_token)
    db.init_schema()

    problems = fetch_problems(db, args)
    if args.limit:
        problems = problems[: args.limit]

    total = len(problems)
    if total == 0:
        print("No problems need processing. Use --overwrite to regenerate.")
        return

    print(f"Found {total} problem(s) to process.")

    if args.provider == "ollama" and not check_ollama(OLLAMA_HOST, model):
        sys.exit(1)

    print(f"Provider: {args.provider}  |  Model: {model}  |  Workers: {args.workers}\n")

    print_lock = threading.Lock()

    def process(i: int, prob: dict) -> bool:
        pid, title, diff, topics = prob["id"], prob["title"], prob["difficulty"], prob["topics"]
        with print_lock:
            print(f"[{i}/{total}] → {title} ({diff})", flush=True)
        t0 = time.time()
        try:
            if args.answers_only:
                answer = generate_answer(args.provider, model, title, diff, topics, groq_key, cerebras_key)
                db.save_answer(pid, answer)
            else:
                hint = generate_hint(args.provider, model, title, diff, topics, groq_key, cerebras_key)
                answer = generate_answer(args.provider, model, title, diff, topics, groq_key, cerebras_key)
                db.save_hint(pid, hint, answer)
            elapsed = time.time() - t0
            with print_lock:
                print(f"[{i}/{total}] ✓ {title} ({diff}) — {elapsed:.1f}s", flush=True)
            return True
        except Exception as e:
            with print_lock:
                print(f"[{i}/{total}] ✗ {title} — {e}", flush=True)
            return False

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process, i, prob): prob
                   for i, prob in enumerate(problems, 1)}
        for fut in as_completed(futures):
            if fut.result(): ok += 1
            else:            fail += 1

    print(f"\nFinished: {ok} succeeded, {fail} failed out of {total} problems.")


if __name__ == "__main__":
    main()
