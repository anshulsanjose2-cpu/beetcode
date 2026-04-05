"""
TursoDB — thin wrapper around the Turso HTTP pipeline API.
Owns schema creation and all domain queries.
"""

import math
import requests


SCHEMA = [
    "DROP TABLE IF EXISTS problem_tags",   # remove old schema if present
    """CREATE TABLE IF NOT EXISTS problems (
        id         INTEGER PRIMARY KEY,
        slug       TEXT    UNIQUE NOT NULL,
        title      TEXT    NOT NULL,
        difficulty TEXT    NOT NULL,
        url        TEXT    NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS topics (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT    UNIQUE NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS problem_topics (
        problem_id INTEGER NOT NULL REFERENCES problems(id),
        topic_id   INTEGER NOT NULL REFERENCES topics(id),
        PRIMARY KEY (problem_id, topic_id)
    )""",
    """CREATE TABLE IF NOT EXISTS companies (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS company_problems (
        company_id     INTEGER NOT NULL REFERENCES companies(id),
        problem_id     INTEGER NOT NULL REFERENCES problems(id),
        timeframe      TEXT    NOT NULL,
        acceptance_pct REAL    NOT NULL DEFAULT 0,
        frequency_pct  REAL    NOT NULL DEFAULT 0,
        PRIMARY KEY (company_id, problem_id, timeframe)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_cp_co_tf  ON company_problems(company_id, timeframe)",
    "CREATE INDEX IF NOT EXISTS idx_cp_prob   ON company_problems(problem_id)",
    "CREATE INDEX IF NOT EXISTS idx_pt_topic  ON problem_topics(topic_id)",
    "CREATE INDEX IF NOT EXISTS idx_prob_diff ON problems(difficulty)",
    # ── User management ───────────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS users (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        username   TEXT    UNIQUE NOT NULL,
        created_at INTEGER DEFAULT (strftime('%s','now'))
    )""",
    """CREATE TABLE IF NOT EXISTS user_problems (
        user_id    INTEGER NOT NULL REFERENCES users(id),
        problem_id INTEGER NOT NULL REFERENCES problems(id),
        solved_at  INTEGER DEFAULT (strftime('%s','now')),
        PRIMARY KEY (user_id, problem_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_up_user ON user_problems(user_id)",
    # ── Solutions ─────────────────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS user_solutions (
        user_id    INTEGER NOT NULL REFERENCES users(id),
        problem_id INTEGER NOT NULL REFERENCES problems(id),
        code       TEXT    NOT NULL DEFAULT '',
        updated_at INTEGER DEFAULT (strftime('%s','now')),
        PRIMARY KEY (user_id, problem_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_usol_user ON user_solutions(user_id)",
]

DROP_ALL = [
    "DROP TABLE IF EXISTS user_solutions",
    "DROP TABLE IF EXISTS user_problems",
    "DROP TABLE IF EXISTS users",
    "DROP TABLE IF EXISTS company_problems",
    "DROP TABLE IF EXISTS problem_topics",
    "DROP TABLE IF EXISTS topics",
    "DROP TABLE IF EXISTS problems",
    "DROP TABLE IF EXISTS companies",
    "DROP TABLE IF EXISTS problem_tags",
]


class TursoDB:
    def __init__(self, url: str, token: str) -> None:
        self.endpoint = url.rstrip("/") + "/v2/pipeline"
        self.headers  = {"Authorization": f"Bearer {token}",
                         "Content-Type":  "application/json"}

    # ── Low-level helpers ──────────────────────────────────────────────────────

    def _arg(self, v):
        """
        Turso HTTP API value encoding:
          integer → {"type":"integer", "value": "<str>"}
          float   → {"type":"float",   "value": <number>}
          text    → {"type":"text",    "value": "<str>"}
        """
        if v is None:           return {"type": "null"}
        if isinstance(v, bool): return {"type": "integer", "value": str(int(v))}
        if isinstance(v, int):  return {"type": "integer", "value": str(v)}
        if isinstance(v, float):
            safe = 0.0 if (math.isnan(v) or math.isinf(v)) else v
            return {"type": "float", "value": safe}
        return {"type": "text", "value": str(v)}

    def _stmt(self, sql: str, args=None) -> dict:
        s: dict = {"sql": sql}
        if args is not None:
            s["args"] = [self._arg(a) for a in args]
        return s

    def _run(self, stmts: list[dict]) -> list[dict]:
        pipeline = [{"type": "execute", "stmt": s} for s in stmts]
        pipeline.append({"type": "close"})
        r = requests.post(self.endpoint, headers=self.headers,
                          json={"requests": pipeline}, timeout=20)
        if not r.ok:
            raise requests.exceptions.HTTPError(
                f"{r.status_code} {r.reason} — {r.text[:400]}", response=r)
        return r.json().get("results", [])

    def _val(self, cell):
        if cell["type"] == "null":    return None
        if cell["type"] == "integer": return int(cell["value"])
        if cell["type"] == "float":   return float(cell["value"])
        return cell["value"]

    def scalar(self, sql: str, args=None):
        res = self._run([self._stmt(sql, args)])
        try:   return self._val(res[0]["response"]["result"]["rows"][0][0])
        except Exception: return None

    def rows(self, sql: str, args=None) -> list[list]:
        res = self._run([self._stmt(sql, args)])
        try:   return res[0]["response"]["result"]["rows"]
        except Exception: return []

    def batch(self, stmts: list[dict], size: int = 500) -> None:
        """Transactional chunks: BEGIN + <size> stmts + COMMIT per network round-trip."""
        if not stmts:
            return
        begin, commit = self._stmt("BEGIN"), self._stmt("COMMIT")
        for i in range(0, len(stmts), size):
            self._run([begin] + stmts[i : i + size] + [commit])

    # ── Schema management ──────────────────────────────────────────────────────

    def init_schema(self) -> None:
        """Create tables and indexes. DDL must run outside a transaction."""
        for sql in SCHEMA:
            self._run([self._stmt(sql)])

    def drop_all(self) -> None:
        for sql in DROP_ALL:
            self._run([self._stmt(sql)])

    def is_seeded(self) -> bool:
        try:
            return (self.scalar("SELECT COUNT(*) FROM companies") or 0) > 0
        except Exception:
            return False

    # ── Domain queries ─────────────────────────────────────────────────────────

    def get_companies(self) -> list[str]:
        return ["All"] + [self._val(r[0]) for r in self.rows("SELECT name FROM companies ORDER BY name")]

    def get_topics(self) -> list[str]:
        return [self._val(r[0]) for r in self.rows("SELECT name FROM topics ORDER BY name")]

    def query_problems(self, companies: list[str], timeframe: str,
                       difficulties: list[str], topics: list[str], search: str) -> list[dict]:
        where = ["cp.timeframe = ?"]
        args: list = [timeframe]

        def _quote(v: str) -> str:
            return "'" + v.lower().replace("'", "''") + "'"

        if companies:
            vals = ", ".join(_quote(c) for c in companies)
            where.append(f"LOWER(c.name) IN ({vals})")

        if difficulties:
            vals = ", ".join(_quote(d) for d in difficulties)
            where.append(f"LOWER(p.difficulty) IN ({vals})")

        if topics:
            vals = ", ".join(_quote(t) for t in topics)
            where.append(f"""p.id IN (
                SELECT pt2.problem_id FROM problem_topics pt2
                JOIN topics t2 ON t2.id = pt2.topic_id
                WHERE LOWER(t2.name) IN ({vals}))""")

        if search and search.strip():
            where.append("p.title LIKE ?")
            args.append(f"%{search.strip()}%")

        sql = f"""
            SELECT p.id, p.slug, p.title, p.url, p.difficulty,
                   cp.acceptance_pct, cp.frequency_pct,
                   GROUP_CONCAT(t.name, '|||') AS topics
            FROM company_problems cp
            JOIN problems  p ON p.id  = cp.problem_id
            JOIN companies c ON c.id  = cp.company_id
            LEFT JOIN problem_topics pt ON pt.problem_id = p.id
            LEFT JOIN topics         t  ON t.id  = pt.topic_id
            WHERE {' AND '.join(where)}
            GROUP BY p.id, cp.acceptance_pct, cp.frequency_pct
            ORDER BY cp.frequency_pct DESC
        """
        return [
            {
                "ID":           self._val(r[0]),
                "slug":         self._val(r[1]) or "",
                "Title":        self._val(r[2]) or "",
                "URL":          self._val(r[3]) or "#",
                "Difficulty":   self._val(r[4]) or "",
                "Acceptance %": self._val(r[5]) or 0.0,
                "Frequency %":  self._val(r[6]) or 0.0,
                "_topics":      [t for t in (self._val(r[7]) or "").split("|||") if t],
            }
            for r in self.rows(sql, args)
        ]

    def stats(self) -> dict[str, int]:
        return {
            t: int(self.scalar(f"SELECT COUNT(*) FROM {t}") or 0)
            for t in ["companies", "problems", "topics", "problem_topics", "company_problems"]
        }

    # ── User management ───────────────────────────────────────────────────────

    def create_or_get_user(self, username: str) -> int:
        """Return user id, creating the user if they don't exist yet."""
        self._run([self._stmt(
            "INSERT OR IGNORE INTO users (username) VALUES (?)", [username]
        )])
        return int(self.scalar("SELECT id FROM users WHERE username = ?", [username]))

    def get_solved_ids(self, user_id: int) -> set[int]:
        return {self._val(r[0]) for r in
                self.rows("SELECT problem_id FROM user_problems WHERE user_id = ?", [user_id])}

    def mark_solved(self, user_id: int, problem_id: int) -> None:
        self._run([self._stmt(
            "INSERT OR IGNORE INTO user_problems (user_id, problem_id) VALUES (?, ?)",
            [user_id, problem_id],
        )])

    def mark_unsolved(self, user_id: int, problem_id: int) -> None:
        self._run([self._stmt(
            "DELETE FROM user_problems WHERE user_id = ? AND problem_id = ?",
            [user_id, problem_id],
        )])

    # ── Solutions ─────────────────────────────────────────────────────────────

    def save_solution(self, user_id: int, problem_id: int, code: str) -> None:
        self._run([self._stmt(
            """INSERT INTO user_solutions (user_id, problem_id, code, updated_at)
               VALUES (?, ?, ?, strftime('%s','now'))
               ON CONFLICT(user_id, problem_id) DO UPDATE SET
                   code = excluded.code,
                   updated_at = strftime('%s','now')""",
            [user_id, problem_id, code],
        )])

    def get_solution(self, user_id: int, problem_id: int) -> str:
        return self.scalar(
            "SELECT code FROM user_solutions WHERE user_id = ? AND problem_id = ?",
            [user_id, problem_id],
        ) or ""
