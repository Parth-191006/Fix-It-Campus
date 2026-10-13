"""Quick checks. Run: python test_smoke.py"""
import os, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ.pop("GEMINI_API_KEY", None)

from streamlit.testing.v1 import AppTest
import ai, store

# 1. demo-mode triage
r = ai.analyze_photo(b"x", "image/jpeg", "sparks from the switch board", "Canteen")
assert r["category"] == "Electrical" and r["safety_risk"] and r["severity"] >= 4, r
assert r["source"].startswith("demo")

# 2. store, duplicates, ordering
s = store.JsonStore()
ts = s.all()
assert len(ts) >= 8
q = sorted([t for t in ts if t["status"] != "Resolved"], key=store.priority_key)
assert q[0]["safety_risk"], "safety issues must come first"
assert store.find_duplicate(ts, "Library - Reading Hall", "Electrical")
print("metrics:", store.metrics(ts))

# 3. every role renders without exceptions
at = AppTest.from_file("app.py", default_timeout=30).run()
assert not at.exception, at.exception
for role in ("Maintenance", "Admin", "Student"):
    at.sidebar.radio[0].set_value(role).run()
    assert not at.exception, (role, at.exception)
print("OK")
