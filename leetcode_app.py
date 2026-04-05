import streamlit as st
from db import TursoDB

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Beetcode", page_icon="🐝", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.lc-header { display:flex;align-items:center;gap:12px;padding:16px 0 24px 0;border-bottom:1px solid #3a3a3a;margin-bottom:24px; }
.lc-logo   { font-size:28px;font-weight:800;color:#FFD700;letter-spacing:-1px; }
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
.solve-btn { cursor:pointer;font-size:16px;user-select:none;text-align:center;width:28px; }
</style>
"""

# ── DB connection (cached per schema version so deploys bust the cache) ──────
_SCHEMA_VERSION = "v3"   # bump this whenever db.py schema changes

@st.cache_resource
def get_db(_v: str = _SCHEMA_VERSION) -> TursoDB:
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

@st.dialog("Solution", width="large")
def solution_dialog(p: dict) -> None:
    pid     = p["ID"]
    user_id = st.session_state["user_id"]
    st.markdown(
        f'**[{p["Title"]}]({p["URL"]})**  '
        f'<span style="color:#888;font-size:13px">— {p["Difficulty"]}</span>',
        unsafe_allow_html=True,
    )
    saved = db.get_solution(user_id, pid)
    mode  = st.radio("", ["View", "Edit"], horizontal=True, label_visibility="collapsed",
                     key=f"dlg_mode_{pid}")

    from streamlit_ace import st_ace
    _ace_kwargs = dict(
        language="python", theme="tomorrow_night",
        font_size=13, tab_size=4,
        show_gutter=True, show_print_margin=False,
        height=420,
    )

    if mode == "View":
        if saved:
            st_ace(value=saved, readonly=True, **_ace_kwargs)
        else:
            st.caption("No solution saved yet. Switch to Edit to add one.")
    else:
        code = st_ace(value=saved, auto_update=True,
                      placeholder="# Paste your Python solution here…", **_ace_kwargs)
        if st.button("💾 Save", type="primary", key=f"dlg_save_{pid}"):
            db.save_solution(user_id, pid, code or "")
            st.toast("Saved!", icon="💾")

def _sync_checkbox(pid: int) -> None:
    """on_change callback: write only the changed checkbox to DB."""
    user_id    = st.session_state["user_id"]
    solved_ids = st.session_state.get("solved_ids", set())
    if st.session_state[f"cb_{pid}"]:
        db.mark_solved(user_id, pid)
        solved_ids.add(pid)
    else:
        db.mark_unsolved(user_id, pid)
        solved_ids.discard(pid)
    st.session_state["solved_ids"] = solved_ids

PAGE_SIZE = 100

# ── App ───────────────────────────────────────────────────────────────────────
db = get_db()

st.markdown(
    '<div class="lc-header">'
    '<div class="lc-logo">🐝 beet<span>code</span></div>'
    '<div style="color:#888;font-size:14px;font-style:italic;">Find what they actually ask</div>'
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

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    # ── User section ──────────────────────────────────────────────────────────
    st.markdown("### 👤 Account")
    if "user_id" not in st.session_state:
        username_input = st.text_input("Username", placeholder="Enter username to sign in")
        if st.button("Sign in / Sign up", use_container_width=True):
            uname = username_input.strip()
            if uname:
                uid = db.create_or_get_user(uname)
                # Clear stale checkbox state from any previous session
                for k in [k for k in st.session_state if k.startswith("cb_")]:
                    del st.session_state[k]
                st.session_state["user_id"]    = uid
                st.session_state["username"]   = uname
                st.session_state["solved_ids"] = db.get_solved_ids(uid)
                st.rerun()
            else:
                st.warning("Please enter a username.")
    else:
        st.success(f"Signed in as **{st.session_state['username']}**")
        if st.button("Sign out", use_container_width=True):
            for k in [k for k in st.session_state if k.startswith("cb_")]:
                del st.session_state[k]
            for k in ("user_id", "username", "solved_ids"):
                st.session_state.pop(k, None)
            st.rerun()

    st.markdown("---")

    # ── Filters ───────────────────────────────────────────────────────────────
    st.markdown("### Filters")
    companies = db.get_companies()
    company      = st.selectbox("Company", companies, index=0)
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

# ── Interactive table fragment (only this section reruns on checkbox click) ────
@st.fragment
def interactive_table(problems):
    solved_ids = st.session_state.get("solved_ids", set())

    # Deduplicate by problem ID (same problem can appear for multiple companies)
    seen = set()
    unique_problems = []
    for p in problems:
        if p["ID"] not in seen:
            seen.add(p["ID"])
            unique_problems.append(p)
    problems = unique_problems

    # Progress bar
    unique_ids   = {p["ID"] for p in problems}
    total_unique = len(unique_ids)
    if total_unique > 0:
        solved_here = len(solved_ids & unique_ids)
        prog_col, btn_col = st.columns([9, 1])
        with prog_col:
            st.progress(solved_here / total_unique,
                        text=f"Solved **{solved_here} / {total_unique}** problems in this view")
        if btn_col.button("Reset", key="reset_progress", help="Unmark all solved in this view"):
            user_id = st.session_state["user_id"]
            for pid in list(solved_ids & unique_ids):
                db.mark_unsolved(user_id, pid)
                solved_ids.discard(pid)
                st.session_state[f"cb_{pid}"] = False
            st.session_state["solved_ids"] = solved_ids
            st.rerun(scope="fragment")

    # Pagination
    total_pages = max(1, (total_unique + PAGE_SIZE - 1) // PAGE_SIZE)
    page = st.session_state.get("table_page", 0)
    page = max(0, min(page, total_pages - 1))
    page_problems = problems[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    # Compact row styling
    st.markdown("""
    <style>
    div[data-testid="stHorizontalBlock"] { gap:0rem;align-items:center;border-bottom:1px solid #2a2a2a;padding:2px 0; }
    div[data-testid="stHorizontalBlock"]:hover { background:#252525; }
    div[data-testid="stCheckbox"] { margin:0;padding:0; }
    div[data-testid="stCheckbox"] label { padding:0; }
    </style>
    """, unsafe_allow_html=True)

    COL_W      = [0.4, 0.5, 3.5, 2.5, 1.2, 1.3, 1.8, 0.9]
    DIFF_COLOR = {"easy": "#2cbb5d", "medium": "#ffa116", "hard": "#ef4743"}

    # Header
    for col, lbl in zip(st.columns(COL_W),
                        ["", "#", "Title", "Topics", "Difficulty", "Acceptance %", "Frequency %", "Solution"]):
        col.markdown(
            f'<span style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.6px">{lbl}</span>',
            unsafe_allow_html=True)
    st.markdown('<hr style="border:none;border-top:2px solid #3a3a3a;margin:2px 0 0 0">',
                unsafe_allow_html=True)

    for p in page_problems:
        pid  = p["ID"]
        cols = st.columns(COL_W)

        cols[0].checkbox("Solved", value=pid in solved_ids, key=f"cb_{pid}",
                         label_visibility="collapsed",
                         on_change=_sync_checkbox, args=(pid,))
        cols[1].markdown(f'<span style="color:#888;font-size:13px">{pid}</span>',
                         unsafe_allow_html=True)
        cols[2].markdown(
            f'<a href="{p["URL"]}" target="_blank" '
            f'style="color:#eff2f6cc;text-decoration:none;font-weight:500">{p["Title"]}</a>',
            unsafe_allow_html=True)
        cols[3].markdown(" ".join(
            f'<span style="color:{TOPIC_COLORS.get(t,"#64748b")};font-size:11px;'
            f'border:1px solid {TOPIC_COLORS.get(t,"#64748b")};border-radius:10px;'
            f'padding:1px 7px;white-space:nowrap">{t}</span>'
            for t in p["_topics"][:3]), unsafe_allow_html=True)
        dc = DIFF_COLOR.get(p["Difficulty"].lower(), "#888")
        cols[4].markdown(
            f'<span style="color:{dc};border:1px solid {dc};border-radius:12px;'
            f'padding:2px 10px;font-size:12px;font-weight:600">{p["Difficulty"].capitalize()}</span>',
            unsafe_allow_html=True)
        cols[5].markdown(
            f'<span style="color:#2cbb5d;font-size:13px">{p["Acceptance %"]:.1f}%</span>',
            unsafe_allow_html=True)
        pct = min(max(float(p["Frequency %"]), 0), 100)
        cols[6].markdown(
            f'<div style="display:flex;align-items:center;gap:6px">'
            f'<div style="background:#2a2a2a;border-radius:4px;height:6px;width:70px;overflow:hidden">'
            f'<div style="height:100%;width:{pct}%;background:#ffa116;border-radius:4px"></div></div>'
            f'<span style="color:#888;font-size:12px">{pct:.0f}%</span></div>',
            unsafe_allow_html=True)
        if cols[7].button("📝", key=f"sol_{pid}", help="View/edit solution"):
            solution_dialog(p)

    # Pagination controls
    if total_pages > 1:
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        pcol1, pcol2, pcol3 = st.columns([1, 3, 1])
        if pcol1.button("← Prev", disabled=(page == 0), key="pg_prev"):
            st.session_state["table_page"] = page - 1
        pcol2.markdown(
            f'<div style="text-align:center;color:#888;font-size:13px;padding-top:6px">'
            f'Page {page + 1} / {total_pages} &nbsp;·&nbsp; '
            f'{page * PAGE_SIZE + 1}–{min((page + 1) * PAGE_SIZE, total_unique)} of {total_unique}</div>',
            unsafe_allow_html=True)
        if pcol3.button("Next →", disabled=(page >= total_pages - 1), key="pg_next"):
            st.session_state["table_page"] = page + 1


# ── Table ─────────────────────────────────────────────────────────────────────
logged_in = "user_id" in st.session_state

if logged_in:
    # Reset to page 0 when the filter combination changes
    filter_key = (company, timeframe, difficulty, topic_filter, search)
    if st.session_state.get("_last_filter") != filter_key:
        st.session_state["_last_filter"] = filter_key
        st.session_state["table_page"] = 0
    interactive_table(problems)
else:
    rows_html = "".join(
        f'<tr>'
        f'<td class="num">{p["ID"]}</td>'
        f'<td class="title"><a href="{p["URL"]}" target="_blank">{p["Title"]}</a></td>'
        f'<td>{topic_chips(p["_topics"])}</td>'
        f'<td>{difficulty_badge(p["Difficulty"])}</td>'
        f'<td><span class="acceptance">{p["Acceptance %"]:.1f}%</span></td>'
        f'<td>{freq_bar(p["Frequency %"])}</td>'
        '</tr>'
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

