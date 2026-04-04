"""
Safe-ish Python code execution in a subprocess.
Runs user code in an isolated process with resource limits and a clean environment.
"""
import json
import os
import subprocess
import sys
import tempfile

TIMEOUT = 5  # seconds

# Resource-limit preamble injected before user code
_RESOURCE_PREAMBLE = """\
import sys, os

# Sandbox: block dangerous builtins
import builtins as _b
_BLOCKED = {"open", "input", "__import__", "compile", "breakpoint"}
_orig_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

def _safe_import(name, *args, **kwargs):
    _NETWORK = {"socket", "urllib", "urllib2", "http", "httplib", "ftplib", "smtplib",
                "telnetlib", "xmlrpc", "imaplib", "poplib", "nntplib", "ssl"}
    if name in _NETWORK:
        raise ImportError(f"Network module '{name}' is blocked in the sandbox.")
    return _orig_import(name, *args, **kwargs)

__builtins__.__import__ = _safe_import  # type: ignore

# Resource limits (no-op on platforms that don't support resource module)
try:
    import resource as _r
    _r.setrlimit(_r.RLIMIT_CPU, (TIMEOUT, TIMEOUT))               # CPU seconds
    _r.setrlimit(_r.RLIMIT_AS,  (256 * 1024 * 1024,) * 2)        # 256 MB RAM
except Exception:
    pass
"""

_TEST_RUNNER = """\

import json as _json, ast as _ast

_results = []
for _call, _exp_repr in _TESTS:
    try:
        _actual = eval(_call)
        try:
            _expected = _ast.literal_eval(_exp_repr)
            _passed = _actual == _expected
        except Exception:
            _passed = repr(_actual).strip() == _exp_repr.strip()
        _results.append({"pass": _passed, "actual": repr(_actual),
                         "expected": _exp_repr, "error": None})
    except Exception as _e:
        _results.append({"pass": False, "actual": None,
                         "expected": _exp_repr, "error": str(_e)})

print(_json.dumps(_results))
"""


def _build_script(user_code: str, test_pairs: list[tuple[str, str]]) -> str:
    preamble = _RESOURCE_PREAMBLE.replace("TIMEOUT", str(TIMEOUT))
    pairs_literal = repr(test_pairs)
    return (
        preamble
        + "\n# ── User code ──────────────────────────────────────────\n"
        + user_code
        + f"\n\n_TESTS = {pairs_literal}\n"
        + _TEST_RUNNER
    )


def _clean_env() -> dict[str, str]:
    """Strip secrets from the subprocess environment."""
    blocked = {"TURSO_AUTH_TOKEN", "TURSO_DATABASE_URL"}
    return {k: v for k, v in os.environ.items() if k not in blocked}


def run_tests(user_code: str, test_lines: list[str]) -> list[dict]:
    """
    Execute user_code against each test line.

    test_lines format:  "functionCall(args) → expected"
    Returns a list of dicts: {pass, actual, expected, error, call}
    """
    # Parse test lines
    test_pairs: list[tuple[str, str]] = []
    parse_errors: list[dict] = []
    for line in test_lines:
        if "→" not in line:
            parse_errors.append({
                "pass": False, "call": line,
                "actual": None, "expected": "?",
                "error": "Missing → separator. Format: call(args) → expected",
            })
            continue
        call, expected = line.split("→", 1)
        test_pairs.append((call.strip(), expected.strip()))

    if not test_pairs:
        return parse_errors

    script = _build_script(user_code, test_pairs)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=TIMEOUT + 1,
                cwd=tmpdir,
                stdin=subprocess.DEVNULL,
                env=_clean_env(),
            )

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if not stdout:
            # Syntax or import error before any test ran
            error_msg = stderr.splitlines()[-1] if stderr else "No output produced"
            return parse_errors + [
                {"pass": False, "call": c, "actual": None,
                 "expected": e, "error": error_msg}
                for c, e in test_pairs
            ]

        raw = json.loads(stdout)
        results = []
        for (call, _), r in zip(test_pairs, raw):
            results.append({
                "pass":     r["pass"],
                "call":     call,
                "actual":   r["actual"],
                "expected": r["expected"],
                "error":    r["error"],
            })
        return parse_errors + results

    except subprocess.TimeoutExpired:
        return parse_errors + [
            {"pass": False, "call": c, "actual": None,
             "expected": e, "error": f"Time Limit Exceeded (>{TIMEOUT}s)"}
            for c, e in test_pairs
        ]
    except Exception as exc:
        return parse_errors + [
            {"pass": False, "call": c, "actual": None,
             "expected": e, "error": str(exc)}
            for c, e in test_pairs
        ]
