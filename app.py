"""FixIt Campus - Streamlit UI.

Three views over one ticket store:
  Student      photo -> Gemini triage -> routed ticket
  Maintenance  priority queue with SLA tracking
  Admin        campus metrics and problem hotspots

All visuals live in ui.py; this file stays about product behaviour.
"""
import base64
import time

import pandas as pd
import streamlit as st

import ui
from ai import TRADES, active_model, analyze_photo, gemini_enabled
from store import (
    SLA_HOURS, age_str, find_duplicate, get_store, make_thumb, metrics,
    new_ticket, priority_key, sla_left_hours,
)

# Edit these to match your campus: the dropdown the student picks from.
LOCATIONS = [
    "Main Building - Staircase", "Main Building - Corridor", "Library - Reading Hall",
    "Hostel Block C - Washroom", "Hostel Block C - Corridor", "Lab Block - Room 204",
    "CS Department - Seminar Hall", "Canteen", "Sports Ground - Pavilion", "Parking Area",
]
SEV_ICON = {5: "🔴", 4: "🟠", 3: "🟡", 2: "🟢", 1: "⚪"}

st.set_page_config(page_title="FixIt Campus", page_icon="🛠️", layout="centered")
ui.inject()


@st.cache_resource
def store():
    return get_store()


db = store()
tickets = db.all()


# ---- small presentation helpers -------------------------------------------

def sev_chip(severity: int) -> str:
    """Severity as a pill. Carries its label and icon, never colour alone."""
    sev = severity if severity in ui.SEV_LABEL else 3
    return ui.chip(ui.SEV_LABEL[sev], ui.SEV_TONE[sev], icon=SEV_ICON[sev])


def thumb_img(t: dict, width: int = 132) -> None:
    if t.get("thumb"):
        st.image(base64.b64decode(t["thumb"]), width=width)
    else:
        st.markdown(
            "<div style='font-size:44px;text-align:center'>🔧</div>",
            unsafe_allow_html=True,
        )


def sla_view(t: dict) -> tuple[str, str]:
    """(sentence, meter html) for a ticket's SLA window."""
    if t["status"] == "Resolved":
        return "resolved", ui.meter(1.0, "low")
    left = sla_left_hours(t)
    used = max(0.0, min(1.0, (SLA_HOURS[t["severity"]] - left) / SLA_HOURS[t["severity"]]))
    if left < 0:
        return f"{abs(left):.0f} h overdue", ui.meter(1.0, "crit")
    tone = "high" if used >= 0.75 else "med" if used >= 0.4 else "low"
    return f"{left:.0f} h left", ui.meter(used, tone)


# ---- sidebar ---------------------------------------------------------------

with st.sidebar:
    ui.brand()
    role = st.radio("View as", ["Student", "Maintenance", "Admin"])
    st.divider()
    st.caption(f"Storage · {db.name}")
    model = active_model()
    ui.html(
        ui.chip(f"Gemini live · {model}" if model else "Gemini live", "low", icon="✦")
        if gemini_enabled()
        else ui.chip("Demo mode — no API key", "med", icon="⚠")
    )
    if st.button("Reset demo data"):
        db.reset()
        for k in ("analysis", "img", "mime", "submitted"):
            st.session_state.pop(k, None)
        st.rerun()


# ---- student ---------------------------------------------------------------

def student_view() -> None:
    ui.hero(
        "See something broken? Snap it.",
        "Take a photo. AI works out what it is, how urgent it is, and who should fix it.",
        kicker="Student report",
    )

    submitted = st.session_state.get("submitted")
    if submitted:
        with st.container(border=True):
            st.success(f"Ticket **{submitted['id']}** is with the **{submitted['trade']}** team.")
            ui.html(
                sev_chip(submitted["severity"])
                + ui.chip(submitted["category"], "info")
                + ui.chip(f"target {SLA_HOURS[submitted['severity']]} h", "neutral")
                + (ui.chip(f"{submitted['reports']} reports", "med")
                   if submitted.get("reports", 1) > 1 else "")
            )
            st.caption("The maintenance team can see this in their queue now.")
        if st.button("Report another problem", type="primary", width="stretch"):
            st.session_state.pop("submitted")
            st.rerun()
        return

    with st.container(border=True):
        mode = st.radio("Photo source", ["Take photo", "Upload"], horizontal=True,
                        label_visibility="collapsed")
        img = (st.camera_input("Photo of the problem") if mode == "Take photo"
               else st.file_uploader("Photo of the problem", type=["jpg", "jpeg", "png"]))
        c1, c2 = st.columns(2)
        with c1:
            location = st.selectbox("Where is it?", LOCATIONS)
        with c2:
            note = st.text_input("Anything to add? (optional)",
                                 placeholder="e.g. sparks when the fan is switched on")

    if img and st.button("Analyze photo", type="primary", width="stretch"):
        data = img.getvalue()
        with st.spinner("Looking at the photo…"):
            st.session_state["analysis"] = analyze_photo(data, img.type or "image/jpeg", note, location)
        st.session_state["img"], st.session_state["loc"], st.session_state["note"] = data, location, note

    a = st.session_state.get("analysis")
    if not a:
        return

    st.divider()
    if not a["is_campus_issue"]:
        st.warning("This doesn't look like a repairable campus problem. Try a clearer photo.")
        return

    with st.container(border=True):
        c1, c2 = st.columns([1, 1.4])
        with c1:
            st.image(st.session_state["img"], width="stretch")
        with c2:
            st.subheader(a["issue"])
            ui.html(
                sev_chip(a["severity"])
                + ui.chip(a["category"], "info")
                + ui.chip(f"sends to {a['trade']}", "neutral")
            )
            if a["safety_risk"]:
                st.error("Safety risk. Keep people away from this area.")
            st.caption(
                f"Confidence {a['confidence']:.0%} · ~{a['est_fix_hours']:g} h of work "
                f"· source: {a['source']}"
            )

    text = st.text_area("Ticket description (edit if the AI got something wrong)",
                        a["complaint_text"], height=100)

    loc = st.session_state["loc"]
    dup = find_duplicate(tickets, loc, a["category"])
    if dup:
        st.info(f"Someone already reported a similar issue here (ticket **{dup['id']}**, "
                f"{dup['reports']} report{'s' if dup['reports'] > 1 else ''}). "
                "Submitting adds your report to it instead of creating a duplicate.")

    if st.button("Submit ticket", type="primary", width="stretch"):
        if dup:
            dup["reports"] = dup.get("reports", 1) + 1
            dup["severity"] = max(dup["severity"], a["severity"])
            db.save(dup)
            st.session_state["submitted"] = dup
        else:
            t = new_ticket(a, loc, text, make_thumb(st.session_state["img"]))
            db.save(t)
            st.session_state["submitted"] = t
        st.session_state.pop("analysis", None)
        st.rerun()


# ---- maintenance -----------------------------------------------------------

def maintenance_view() -> None:
    ui.hero("Maintenance queue",
            "Safety risks first, then severity, then most-reported.",
            kicker="Maintenance")

    c1, c2 = st.columns([2, 1])
    with c1:
        trade = st.selectbox("Show jobs for", ["All trades"] + TRADES)
    with c2:
        show_done = st.toggle("Show resolved", False)

    queue = [t for t in tickets if (show_done or t["status"] != "Resolved")
             and (trade == "All trades" or t["trade"] == trade)]
    queue.sort(key=lambda t: (t["status"] == "Resolved",) + priority_key(t))

    if not queue:
        st.success("Nothing in the queue. 🎉")
        return

    for t in queue:
        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            with c1:
                thumb_img(t)
            with c2:
                st.markdown(
                    f"**{t['issue']}** &nbsp; <span class='hf-mono'>#{t['id']}</span>",
                    unsafe_allow_html=True,
                )
                ui.html(
                    sev_chip(t["severity"])
                    + ui.chip(t["category"], "info")
                    + ui.chip(t["location"], "neutral")
                )
                sla_text, meter = sla_view(t)
                ui.html(meter)
                extra = f" · 👥 {t['reports']} reports" if t.get("reports", 1) > 1 else ""
                st.caption(f"{t['status']} · opened {age_str(time.time() - t['created'])} ago "
                           f"· SLA: {sla_text}{extra}")
                if t["safety_risk"] and t["status"] != "Resolved":
                    st.error("Safety risk", icon="⚠️")
                b1, b2, _ = st.columns([1, 1, 2])
                if t["status"] == "Open" and b1.button("Start", key=f"s{t['id']}"):
                    t["status"] = "In progress"
                    db.save(t)
                    st.rerun()
                if t["status"] != "Resolved" and b2.button("Resolve", key=f"r{t['id']}", type="primary"):
                    t["status"], t["resolved_at"] = "Resolved", time.time()
                    db.save(t)
                    st.rerun()


# ---- admin -----------------------------------------------------------------

def admin_view() -> None:
    ui.hero("Campus overview",
            "Where problems cluster, what breaks most, and how fast we close them.",
            kicker="Admin")

    m = metrics(tickets)
    c = st.columns(4)
    c[0].metric("Open tickets", m["open"])
    c[1].metric("Critical open", m["critical"])
    c[2].metric("SLA breaches", m["breaches"])
    c[3].metric("Avg fix time", f"{m['avg_resolution_h']:.0f} h")

    ui.html(ui.chip(f"{m['merged']} duplicate reports merged into existing tickets",
                    "info", icon="👥"))

    df = pd.DataFrame(tickets)
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.subheader("Where problems cluster")
        st.bar_chart(
            df.groupby("location")["reports"].sum().sort_values(ascending=False),
            width="stretch",
        )
    with c2, st.container(border=True):
        st.subheader("What breaks most")
        st.bar_chart(df["category"].value_counts(), width="stretch")

    export = df.drop(columns=["thumb"]).to_csv(index=False).encode()
    st.download_button("Download all tickets (CSV)", export, "tickets.csv", "text/csv",
                       width="stretch")


{"Student": student_view, "Maintenance": maintenance_view, "Admin": admin_view}[role]()
