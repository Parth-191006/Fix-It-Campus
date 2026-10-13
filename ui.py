"""Presentation layer for FixIt Campus.

Keeps every visual concern in one place so app.py reads as product logic:

    ui.inject()                     install the stylesheet once per run
    ui.hero(...)                    page title block
    ui.chip(...) / ui.sev_chip(...) small status pills (return HTML)
    ui.meter(...)                   SLA progress bar (returns HTML)
    ui.brand(), ui.status_chip(...) sidebar furniture

Deliberately dependency-free: plain CSS against Streamlit's own DOM plus a
handful of classed spans, so nothing here can break the Cloud build.
"""
from html import escape

import streamlit as st

# Severity -> visual tone. Colour alone never carries the meaning: every chip
# also prints its label, so the scale still reads for colour-blind users.
SEV_LABEL = {5: "Critical", 4: "High", 3: "Medium", 2: "Low", 1: "Minor"}
SEV_TONE = {5: "crit", 4: "high", 3: "med", 2: "low", 1: "minor"}

# Reported-status tone for tickets.
STATUS_TONE = {"Open": "info", "In progress": "med", "Resolved": "low"}

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --hf-bg: #0b1120;
  --hf-accent: #f97316;
  --hf-line: rgba(148, 163, 184, .16);
  --hf-card: linear-gradient(180deg, rgba(148,163,184,.07), rgba(148,163,184,.02));
}

html, body, [class*="css"], .stApp {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

/* App canvas: two soft colour washes over deep navy. */
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(1100px 560px at 12% -12%, rgba(249,115,22,.10), transparent 60%),
    radial-gradient(900px 480px at 98% -6%, rgba(56,189,248,.09), transparent 55%),
    var(--hf-bg);
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stDecoration"] { display: none; }  /* the rainbow strip */

/* Sidebar */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #111b30 0%, #0b1323 100%);
  border-right: 1px solid var(--hf-line);
}
[data-testid="stSidebar"] .stButton > button { width: 100%; }

/* Type */
h1 { font-weight: 800 !important; letter-spacing: -.025em; }
h2, h3 { font-weight: 700 !important; letter-spacing: -.015em; }
[data-testid="stCaptionContainer"] { opacity: .72; }

/* Buttons */
.stButton > button, .stDownloadButton > button {
  border-radius: 12px;
  font-weight: 600;
  border: 1px solid rgba(148,163,184,.24);
  background: rgba(148,163,184,.08);
  transition: transform .12s ease, box-shadow .12s ease, background .12s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  transform: translateY(-1px);
  border-color: rgba(148,163,184,.42);
  box-shadow: 0 8px 20px rgba(0,0,0,.38);
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
  background: linear-gradient(135deg, #fb923c, #ea580c);
  border: 1px solid rgba(249,115,22,.6);
  color: #fff;
}
.stButton > button[kind="primary"]:hover {
  box-shadow: 0 10px 26px rgba(249,115,22,.38);
}

/* Inputs */
.stTextInput input, .stTextArea textarea, [data-baseweb="select"] > div {
  border-radius: 10px !important;
  background: rgba(148,163,184,.06) !important;
  border-color: rgba(148,163,184,.20) !important;
}

/* Bordered containers wrapped by st.container(border=True) become cards. */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: 16px !important;
  border: 1px solid var(--hf-line) !important;
  background: var(--hf-card);
}

/* Metrics */
[data-testid="stMetric"] {
  background: var(--hf-card);
  border: 1px solid var(--hf-line);
  border-radius: 16px;
  padding: 14px 16px;
}
[data-testid="stMetricLabel"] { opacity: .78; font-weight: 600; }
[data-testid="stMetricValue"] { font-weight: 800; letter-spacing: -.02em; }

/* Alerts */
[data-testid="stAlert"] { border-radius: 14px; border: 1px solid var(--hf-line); }

/* ---- custom components ------------------------------------------------- */

.hf-brand { display: flex; align-items: center; gap: .7rem; padding: .2rem 0 1rem; }
.hf-brand-mark {
  width: 44px; height: 44px; flex: 0 0 44px;
  display: grid; place-items: center; font-size: 1.35rem;
  border-radius: 13px;
  background: linear-gradient(135deg, #fb923c, #ea580c);
  box-shadow: 0 8px 20px rgba(249,115,22,.30);
}
.hf-brand-name { font-weight: 800; font-size: 1.06rem; letter-spacing: -.02em; }
.hf-brand-tag { font-size: .72rem; opacity: .62; letter-spacing: .09em; text-transform: uppercase; }

.hf-hero { margin: .1rem 0 1.1rem; }
.hf-hero-kicker {
  font-size: .72rem; font-weight: 700; letter-spacing: .14em;
  text-transform: uppercase; color: var(--hf-accent); opacity: .95;
}
.hf-hero-title {
  font-size: 2.05rem; font-weight: 800; letter-spacing: -.032em;
  line-height: 1.12; margin: .3rem 0 .35rem;
}
.hf-hero-sub { opacity: .74; font-size: .95rem; line-height: 1.5; max-width: 62ch; }

.hf-chip {
  display: inline-flex; align-items: center; gap: .32rem;
  padding: .2rem .58rem; margin: 0 .26rem .3rem 0;
  border-radius: 999px; font-size: .74rem; font-weight: 700;
  letter-spacing: .03em; text-transform: uppercase;
  border: 1px solid transparent; white-space: nowrap;
}
.hf-chip.crit   { background: rgba(239,68,68,.16);  color: #fca5a5; border-color: rgba(239,68,68,.42); }
.hf-chip.high   { background: rgba(249,115,22,.16); color: #fdba74; border-color: rgba(249,115,22,.42); }
.hf-chip.med    { background: rgba(234,179,8,.16);  color: #fde68a; border-color: rgba(234,179,8,.40); }
.hf-chip.low    { background: rgba(34,197,94,.15);  color: #86efac; border-color: rgba(34,197,94,.38); }
.hf-chip.minor  { background: rgba(148,163,184,.15);color: #cbd5e1; border-color: rgba(148,163,184,.34); }
.hf-chip.info   { background: rgba(56,189,248,.15); color: #7dd3fc; border-color: rgba(56,189,248,.38); }
.hf-chip.neutral{ background: rgba(148,163,184,.13);color: #cbd5e1; border-color: rgba(148,163,184,.3); }

.hf-meter {
  height: 6px; border-radius: 999px; overflow: hidden;
  background: rgba(148,163,184,.18); margin: .45rem 0 .1rem;
}
.hf-meter-fill { display: block; height: 100%; border-radius: 999px; }
.hf-meter-fill.crit { background: linear-gradient(90deg,#ef4444,#b91c1c); }
.hf-meter-fill.high { background: linear-gradient(90deg,#fb923c,#ea580c); }
.hf-meter-fill.med  { background: linear-gradient(90deg,#facc15,#ca8a04); }
.hf-meter-fill.low  { background: linear-gradient(90deg,#4ade80,#16a34a); }
.hf-meter-fill.minor{ background: linear-gradient(90deg,#94a3b8,#64748b); }

.hf-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .82rem; opacity: .85; }
"""


def inject() -> None:
    """Install the stylesheet. Cheap and idempotent, so call it near the top."""
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)


def _esc(text: object) -> str:
    return escape(str(text), quote=True)


def brand() -> None:
    st.markdown(
        """
        <div class="hf-brand">
          <div class="hf-brand-mark">&#128736;</div>
          <div>
            <div class="hf-brand-name">FixIt Campus</div>
            <div class="hf-brand-tag">Report &middot; Route &middot; Resolve</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str = "", kicker: str = "") -> None:
    parts = ['<div class="hf-hero">']
    if kicker:
        parts.append(f'<div class="hf-hero-kicker">{_esc(kicker)}</div>')
    parts.append(f'<div class="hf-hero-title">{_esc(title)}</div>')
    if subtitle:
        parts.append(f'<div class="hf-hero-sub">{_esc(subtitle)}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def chip(text: str, tone: str = "neutral", icon: str = "") -> str:
    """A status pill. Returns HTML so callers can compose several in one row."""
    glyph = f"{icon} " if icon else ""
    return f'<span class="hf-chip {tone}">{glyph}{_esc(text)}</span>'


def sev_chip(severity: int) -> str:
    sev = severity if severity in SEV_LABEL else 3
    return chip(f"{SEV_LABEL[sev]}", SEV_TONE[sev])


def status_chip(status: str) -> str:
    return chip(status, STATUS_TONE.get(status, "neutral"))


def meter(fraction: float, tone: str) -> str:
    """SLA progress bar. fraction is how much of the SLA window is used up."""
    pct = max(0.0, min(1.0, float(fraction))) * 100
    return (
        f'<div class="hf-meter"><span class="hf-meter-fill {tone}" '
        f'style="width:{pct:.1f}%"></span></div>'
    )


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)
