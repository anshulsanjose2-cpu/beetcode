"""
Fetch problem details from LeetCode's GraphQL API on demand.
Results are NOT persisted — cached in st.session_state per session.
"""
import re
import requests

GRAPHQL_URL = "https://leetcode.com/graphql"

_DETAIL_QUERY = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    content
    exampleTestcases
    codeSnippets {
      lang
      langSlug
      code
    }
  }
}
"""

_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent":   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer":      "https://leetcode.com/",
}


def fetch_problem_detail(slug: str) -> dict | None:
    """
    Returns dict with keys:
      content           – raw HTML of the problem statement (may be empty if auth required)
      python_template   – Python3 starter code snippet
      example_inputs    – raw exampleTestcases string (newline-separated arguments)
    Returns None on network failure.
    """
    try:
        r = requests.post(
            GRAPHQL_URL,
            json={"query": _DETAIL_QUERY, "variables": {"titleSlug": slug}},
            headers={**_HEADERS, "Referer": f"https://leetcode.com/problems/{slug}/"},
            timeout=10,
        )
        if not r.ok:
            return None
        q = r.json().get("data", {}).get("question") or {}

        snippets  = q.get("codeSnippets") or []
        py_code   = next((s["code"] for s in snippets if s["langSlug"] == "python3"), "")

        return {
            "content":         q.get("content") or "",
            "python_template": py_code,
            "example_inputs":  q.get("exampleTestcases") or "",
        }
    except Exception:
        return None


# ── HTML helpers ──────────────────────────────────────────────────────────────

def strip_html(html: str) -> str:
    """Convert LeetCode HTML to plain text, preserving code blocks."""
    text = re.sub(r"<pre>(.*?)</pre>", lambda m: m.group(1), html, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&") \
               .replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def description_html(content: str) -> str:
    """Wrap LeetCode HTML in a dark-styled page for st.html() rendering."""
    return f"""
<style>
  body  {{ background:#1a1a1a;color:#d4d4d4;font-family:-apple-system,BlinkMacSystemFont,sans-serif;
           font-size:14px;line-height:1.7;padding:12px 16px;margin:0; }}
  pre   {{ background:#282828;border-radius:6px;padding:12px;overflow-x:auto; }}
  code  {{ font-family:'JetBrains Mono','Fira Code',monospace;font-size:12px; }}
  strong {{ color:#eff2f6; }}
  a     {{ color:#ffa116; }}
  ul,ol {{ padding-left:20px; }}
</style>
{content}
"""
