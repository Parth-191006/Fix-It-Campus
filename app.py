import base64
import time

import pandas as pd
import streamlit as st

from ai import analyze_photo, gemini_enabled, CATEGORIES, TRADES
from store import (
    get_store, new_ticket, find_duplicate, make_thumb, priority_key,
    sla_left_hours, age_str, metrics, SLA_HOURS,
)

# Edit these to match your campus: the dropdown the student picks from.
LOCATIONS = [
    "Main Building - Staircase", "Main Building - Corridor", "Library - Reading Hall",
    "Hostel Block C - Washroom", "Hostel Block C - Corridor", "Lab Block - Room 204",
    "CS Department - Seminar Hall", "Canteen", "Sports Ground - Pavilion", "Parking Area",
]
SEV = {5: "🔴 Critical", 4: "🟠 High", 3: "🟡 Medium", 2: "🟢 Low", 1: "⚪ Minor"}

st.set_page_config(page_title="FixIt Campus", page_icon="🛠️", layout="centered")


@st.cache_resource
def store():
    return get_store()


db = store()

# ---- sidebar ---------------------------------------------------------------
st.sidebar.title("🛠️ FixIt Campus")
role = st.sidebar.radio("View as", ["Student", "Maintenance", "Admin"])
st.sidebar.caption(f"Storage: {db.name}")
st.sidebar.caption("AI: Gemini live" if gemini_enabled() else "AI: demo mode (set GEMINI_API_KEY)")
if st.sidebar.button("Reset demo data"):
    db.reset()
    for k in ("analysis", "img", "mime", "submitted"):
        st.session_state.pop(k, None)
    st.rerun()

tickets = db.all()


def thumb_img(t, width=140):
    if t.get("thumb"):
        st.image(base64.b64decode(t["thumb"]), width=width)
    else:
        st.markdown("<div style='font-size:48px;text-align:center'>🔧</div>", unsafe_allow_html=True)


# ---- student ---------------------------------------------------------------
def student_view():
    st.title("See something broken? Snap it.")
    st.caption("Take a photo. AI works out what it is, how urgent it is, and who should fix it.")

    if st.session_state.get("submitted"):
        t = st.session_state["submitted"]
        st.success(f"Ticket **{t['id']}** is with the **{t['trade']}** team.")
        st.info(f"Priority: {SEV[t['severity']]} · target fix time: {SLA_HOURS[t['severity']]} h")
        if st.button("Report another problem"):
            st.session_state.pop("submitted")
            st.rerun()
        return

    mode = st.radio("Photo", ["Take photo", "Upload"], horizontal=True, label_visibility="collapsed")
    img = st.camera_input("Photo of the problem") if mode == "Take photo" else \
        st.file_uploader("Photo of the problem", type=["jpg", "jpeg", "png"])
    location = st.selectbox("Where is it?", LOCATIONS)
    note = st.text_input("Anything to add? (optional)", placeholder="e.g. sparks when the fan is switched on")

    if img and st.button("Analyze", type="primary"):
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

    c1, c2 = st.columns([1, 1.4])
    with c1:
        st.image(st.session_state["img"], use_container_width=True)
    with c2:
        st.subheader(a["issue"])
        st.markdown(f"**{SEV[a['severity']]}** · {a['category']} · sends to **{a['trade']}**")
        if a["safety_risk"]:
            st.error("⚠️ Safety risk. Keep people away from this area.")
        st.caption(f"Confidence {a['confidence']:.0%} · ~{a['est_fix_hours']:g} h of work · source: {a['source']}")

    text = st.text_area("Ticket description (edit if the AI got something wrong)", a["complaint_text"], height=100)

    loc = st.session_state["loc"]
    dup = find_duplicate(tickets, loc, a["category"])
    if dup:
        st.info(f"Someone already reported a similar issue here (ticket **{dup['id']}**, "
                f"{dup['reports']} report{'s' if dup['reports'] > 1 else ''}). "
                "Submitting adds your report to it instead of creating a duplicate.")

    if st.button("Submit ticket", type="primary"):
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
def maintenance_view():
    st.title("Maintenance queue")
    st.caption("Safety risks first, then severity, then most-reported.")
    trade = st.selectbox("Show jobs for", ["All trades"] + TRADES)
    show_done = st.toggle("Show resolved", False)

    queue = [t for t in tickets if (show_done or t["status"] != "Resolved")
             and (trade == "All trades" or t["trade"] == trade)]
    queue.sort(key=lambda t: (t["status"] == "Resolved",) + priority_key(t))
    if not queue:
        st.success("Nothing in the queue. 🎉")

    for t in queue:
        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            with c1:
                thumb_img(t)
            with c2:
                st.markdown(f"**{t['issue']}**  ·  `{t['id']}`")
                st.markdown(f"{SEV[t['severity']]} · {t['category']} · {t['location']}")
                left = sla_left_hours(t)
                sla = "resolved" if t["status"] == "Resolved" else \
                    (f"⏰ **{abs(left):.0f} h overdue**" if left < 0 else f"{left:.0f} h left")
                extra = f" · 👥 {t['reports']} reports" if t.get("reports", 1) > 1 else ""
                st.caption(f"{t['status']} · opened {age_str(time.time() - t['created'])} ago · SLA: {sla}{extra}")
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
def admin_view():
    st.title("Campus overview")
    m = metrics(tickets)
    c = st.columns(4)
    c[0].metric("Open tickets", m["open"])
    c[1].metric("Critical open", m["critical"])
    c[2].metric("SLA breaches", m["breaches"])
    c[3].metric("Avg fix time", f"{m['avg_resolution_h']:.0f} h")
    st.caption(f"{m['merged']} duplicate reports were merged into existing tickets instead of creating extra work.")

    df = pd.DataFrame(tickets)
    st.subheader("Where problems cluster")
    st.bar_chart(df.groupby("location")["reports"].sum().sort_values(ascending=False))
    st.subheader("What breaks most")
    st.bar_chart(df["category"].value_counts())

    export = df.drop(columns=["thumb"]).to_csv(index=False).encode()
    st.download_button("Download all tickets (CSV)", export, "tickets.csv", "text/csv")


{"Student": student_view, "Maintenance": maintenance_view, "Admin": admin_view}[role]()
