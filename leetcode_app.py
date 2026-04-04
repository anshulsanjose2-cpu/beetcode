import streamlit as st
from db import TursoDB

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="LeetCode Company Questions", page_icon="💻", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.lc-header { display:flex;align-items:center;gap:12px;padding:16px 0 24px 0;border-bottom:1px solid #3a3a3a;margin-bottom:24px; }
.lc-logo   { font-size:28px;font-weight:800;color:#ffa116;letter-spacing:-1px; }
.lc-logo span { color:#ffffff; }
.stats-bar { display:flex;gap:24px;padding:12px 16px;background:#282828;border-radius:8px;margin-bottom:20px; }
.stat-item { text-align:center; }
.stat-num  { font-size:22px;font-weight:700;color:#ffffff; }
.stat-lbl  { font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px; }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
TIMEFRAME_KEYS = {
    "All Time":           "all",
    "Last 6 Months":      "six-months",
    "Last 3 Months":      "three-months",
    "Last 30 Days":       "thirty-days",
    "More than 6 Months": "more-than-six-months",
}

TOPIC_COLORS: dict[str, str] = {
    "Array":               "#3b82f6", "String":              "#8b5cf6",
    "Linked List":         "#ec4899", "Tree":                "#10b981",
    "Graph":               "#f59e0b", "Dynamic Programming": "#ef4444",
    "Backtracking":        "#f97316", "Binary Search":       "#06b6d4",
    "Stack":               "#84cc16", "Heap":                "#a855f7",
    "Trie":                "#14b8a6", "Sliding Window":      "#3b82f6",
    "Two Pointers":        "#6366f1", "Greedy":              "#fbbf24",
    "Intervals":           "#fb923c", "Bit Manipulation":    "#64748b",
    "Math":                "#94a3b8", "Sorting":             "#22d3ee",
    "Hash Table":          "#4ade80", "Monotonic Stack":     "#c084fc",
    "Union Find":          "#f43f5e", "Segment Tree":        "#0ea5e9",
}

TABLE_CSS = """
<style>
* { box-sizing:border-box;margin:0;padding:0; }
body { background:transparent;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.lc-table { width:100%;border-collapse:collapse; }
.lc-table thead tr { background:#282828;border-bottom:2px solid #3a3a3a; }
.lc-table th { padding:10px 14px;text-align:left;font-size:12px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.6px; }
.lc-table tbody tr { border-bottom:1px solid #2a2a2a; }
.lc-table tbody tr:hover { background:#252525; }
.lc-table td { padding:9px 14px;font-size:14px;color:#eff2f6aa;vertical-align:middle; }
.lc-table td.title a { color:#eff2f6cc;text-decoration:none;font-weight:500; }
.lc-table td.title a:hover { color:#ffa116; }
.lc-table td.num { color:#888;font-size:13px; }
.badge { display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600; }
.badge-easy   { background:#1a3a2a;color:#2cbb5d;border:1px solid #2cbb5d; }
.badge-medium { background:#3a2e0a;color:#ffa116;border:1px solid #ffa116; }
.badge-hard   { background:#3a1212;color:#ef4743;border:1px solid #ef4743; }
.topic-chip { display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:500;border:1px solid;background:transparent;margin-right:3px;white-space:nowrap; }
.freq-bar-wrap { background:#2a2a2a;border-radius:4px;height:6px;width:80px;overflow:hidden;display:inline-block;vertical-align:middle; }
.freq-bar { height:100%;border-radius:4px;background:#ffa116; }
.acceptance { color:#2cbb5d;font-size:13px; }
</style>
"""

# ── DB connection (cached for the Streamlit process lifetime) ─────────────────
@st.cache_resource
def get_db() -> TursoDB:
    db = TursoDB(
        url=st.secrets["TURSO_DATABASE_URL"],
        token=st.secrets["TURSO_AUTH_TOKEN"],
    )
    db.init_schema()
    return db

# ── Rendering helpers ─────────────────────────────────────────────────────────
def difficulty_badge(d: str) -> str:
    cls = {"easy": "badge-easy", "medium": "badge-medium", "hard": "badge-hard"}.get(
        str(d).lower(), "badge-easy")
    return f'<span class="badge {cls}">{str(d).capitalize()}</span>'

def topic_chips(topics: list[str]) -> str:
    return " ".join(
        f'<span class="topic-chip" style="border-color:{TOPIC_COLORS.get(t,"#64748b")};'
        f'color:{TOPIC_COLORS.get(t,"#64748b")}">{t}</span>'
        for t in topics[:3]
    )

def freq_bar(val: float) -> str:
    pct = min(max(float(val), 0), 100)
    return (f'<div class="freq-bar-wrap"><div class="freq-bar" style="width:{pct}%"></div></div>'
            f' <span style="color:#888;font-size:12px">{pct:.0f}%</span>')

# ── App ───────────────────────────────────────────────────────────────────────
db = get_db()

st.markdown(
    '<div class="lc-header">'
    '<div class="lc-logo">leet<span>code</span></div>'
    '<div style="color:#888;font-size:14px;">Company-wise Interview Questions</div>'
    '</div>',
    unsafe_allow_html=True,
)

# ── Gate: DB not seeded ───────────────────────────────────────────────────────
if not db.is_seeded():
    st.error(
        "Database is empty. Run the seeder locally to populate it:\n\n"
        "```bash\npython seed.py\n```\n\n"
        "The deployed app reads from Turso — once seeded locally, it will work here too."
    )
    st.stop()

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Filters")
    companies = db.get_companies()
    company   = st.selectbox("Company", companies, index=0)
    timeframe    = st.selectbox("Timeframe", list(TIMEFRAME_KEYS.keys()))
    difficulty   = st.selectbox("Difficulty", ["All", "Easy", "Medium", "Hard"])
    topic_filter = st.selectbox("Topic", ["All"] + db.get_topics())
    search       = st.text_input("Search by title", placeholder="e.g. Two Sum")

    st.markdown("---")
    st.caption("**DB stats**")
    for table, count in db.stats().items():
        st.caption(f"{table}: {count:,}")

    st.markdown("---")
    st.caption("To refresh data, run `python seed.py --reset` locally.")

# ── Query ─────────────────────────────────────────────────────────────────────
problems = db.query_problems(
    company, TIMEFRAME_KEYS[timeframe], difficulty, topic_filter, search
)

# ── Stats bar ─────────────────────────────────────────────────────────────────
total    = len(problems)
easy_n   = sum(1 for p in problems if p["Difficulty"].lower() == "easy")
medium_n = sum(1 for p in problems if p["Difficulty"].lower() == "medium")
hard_n   = sum(1 for p in problems if p["Difficulty"].lower() == "hard")

st.markdown(f"""
<div class="stats-bar">
  <div class="stat-item"><div class="stat-num">{total}</div><div class="stat-lbl">Problems</div></div>
  <div class="stat-item"><div class="stat-num" style="color:#2cbb5d">{easy_n}</div><div class="stat-lbl">Easy</div></div>
  <div class="stat-item"><div class="stat-num" style="color:#ffa116">{medium_n}</div><div class="stat-lbl">Medium</div></div>
  <div class="stat-item"><div class="stat-num" style="color:#ef4743">{hard_n}</div><div class="stat-lbl">Hard</div></div>
  <div class="stat-item" style="margin-left:auto;">
    <div class="stat-num" style="color:#ffa116;font-size:16px;">{"ALL COMPANIES" if company == "All" else company.upper()}</div>
    <div class="stat-lbl">{timeframe}</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Table ─────────────────────────────────────────────────────────────────────
rows_html = "".join(
    f"""<tr>
      <td class="num">{p["ID"]}</td>
      <td class="title"><a href="{p["URL"]}" target="_blank">{p["Title"]}</a></td>
      <td>{topic_chips(p["_topics"])}</td>
      <td>{difficulty_badge(p["Difficulty"])}</td>
      <td><span class="acceptance">{p["Acceptance %"]:.1f}%</span></td>
      <td>{freq_bar(p["Frequency %"])}</td>
    </tr>"""
    for p in problems
)

st.html(TABLE_CSS + f"""
<table class="lc-table">
  <thead><tr>
    <th>#</th><th>Title</th><th>Topics</th>
    <th>Difficulty</th><th>Acceptance</th><th>Frequency</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>
""")

if total == 0:
    st.info("No problems match your filters.")
