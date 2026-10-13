"""Ticket storage. Firestore when USE_FIRESTORE=1, otherwise a local JSON file."""
import base64
import io
import json
import os
import time
import uuid
from pathlib import Path

from PIL import Image

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
FILE = DATA_DIR / "tickets.json"

# Hours allowed before a ticket counts as an SLA breach, by severity.
SLA_HOURS = {5: 4, 4: 24, 3: 48, 2: 96, 1: 168}
HOUR = 3600


def make_thumb(image_bytes: bytes) -> str | None:
    """Small JPEG (base64) so tickets stay tiny enough for Firestore documents."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img.thumbnail((480, 480))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _seed() -> list[dict]:
    """Realistic starter data so the demo never looks empty. Edit locations to match your campus."""
    now = time.time()

    def t(hrs_ago, loc, cat, issue, sev, safety, trade, status, reports=1, fix_hrs=2, resolved_after=None):
        return {
            "id": uuid.uuid4().hex[:6].upper(), "created": now - hrs_ago * HOUR,
            "location": loc, "category": cat, "issue": issue, "severity": sev,
            "safety_risk": safety, "trade": trade, "est_fix_hours": fix_hrs,
            "text": f"{issue} reported at {loc}.", "status": status, "reports": reports,
            "thumb": None, "source": "seed",
            "resolved_at": (now - hrs_ago * HOUR + resolved_after * HOUR) if resolved_after else None,
        }

    return [
        t(3, "Main Building - Staircase", "Electrical", "Exposed wiring at switchboard", 5, True, "Electrician", "Open", 3, 1),
        t(30, "Library - Reading Hall", "Electrical", "Flickering tube lights", 2, False, "Electrician", "Open", 4, 1),
        t(20, "Hostel Block C - Washroom", "Plumbing", "Leaking tap flooding floor", 3, False, "Plumber", "In progress", 2, 2),
        t(52, "Sports Ground - Pavilion", "Civil/Structural", "Cracked concrete step", 4, True, "Mason", "Open", 1, 6),
        t(10, "Lab Block - Room 204", "Furniture", "Broken lab bench stool", 2, False, "Carpenter", "Open", 1, 1),
        t(70, "CS Department - Seminar Hall", "HVAC/Cooling", "AC not cooling", 3, False, "AC Technician", "Open", 5, 3),
        t(120, "Canteen", "Plumbing", "Water cooler not dispensing", 3, False, "Plumber", "Resolved", 2, 2, resolved_after=9),
        t(96, "Hostel Block C - Corridor", "Cleaning/Sanitation", "Overflowing dustbin", 2, False, "Housekeeping", "Resolved", 1, 1, resolved_after=5),
        t(150, "Library - Reading Hall", "Furniture", "Wobbly study table", 2, False, "Carpenter", "Resolved", 1, 1, resolved_after=30),
    ]


class JsonStore:
    name = f"local file ({FILE})"

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not FILE.exists():
            self._write(_seed())

    def _write(self, tickets):
        FILE.write_text(json.dumps(tickets))

    def all(self):
        return json.loads(FILE.read_text())

    def save(self, ticket):
        tickets = [x for x in self.all() if x["id"] != ticket["id"]]
        tickets.append(ticket)
        self._write(tickets)

    def reset(self):
        self._write(_seed())


class FirestoreStore:
    name = "Firestore"

    def __init__(self):
        from google.cloud import firestore
        self.col = firestore.Client().collection("tickets")
        if not any(True for _ in self.col.limit(1).stream()):
            self.reset()

    def all(self):
        return [d.to_dict() for d in self.col.stream()]

    def save(self, ticket):
        self.col.document(ticket["id"]).set(ticket)

    def reset(self):
        for d in self.col.stream():
            d.reference.delete()
        for t in _seed():
            self.save(t)


def get_store():
    if os.getenv("USE_FIRESTORE") == "1":
        try:
            return FirestoreStore()
        except Exception:
            pass  # fall through to local file so the demo still runs
    return JsonStore()


# ---- ticket logic ----------------------------------------------------------

def new_ticket(analysis: dict, location: str, text: str, thumb: str | None) -> dict:
    return {
        "id": uuid.uuid4().hex[:6].upper(), "created": time.time(),
        "location": location, "category": analysis["category"], "issue": analysis["issue"],
        "severity": analysis["severity"], "safety_risk": analysis["safety_risk"],
        "trade": analysis["trade"], "est_fix_hours": analysis["est_fix_hours"],
        "text": text, "status": "Open", "reports": 1, "thumb": thumb,
        "source": analysis.get("source", ""), "resolved_at": None,
    }


def find_duplicate(tickets: list[dict], location: str, category: str) -> dict | None:
    for t in tickets:
        if t["status"] != "Resolved" and t["location"] == location and t["category"] == category:
            return t
    return None


def sla_left_hours(t: dict) -> float:
    return SLA_HOURS[t["severity"]] - (time.time() - t["created"]) / HOUR


def priority_key(t: dict):
    """Sort order for the maintenance queue: safety first, then severity, then most-reported, then oldest."""
    return (not t["safety_risk"], -t["severity"], -t.get("reports", 1), t["created"])


def age_str(seconds: float) -> str:
    h = seconds / HOUR
    return f"{int(seconds // 60)} min" if h < 1 else f"{h:.0f} h" if h < 48 else f"{h / 24:.0f} d"


def metrics(tickets: list[dict]) -> dict:
    open_t = [t for t in tickets if t["status"] != "Resolved"]
    done = [t for t in tickets if t["status"] == "Resolved" and t.get("resolved_at")]
    avg = sum(t["resolved_at"] - t["created"] for t in done) / len(done) / HOUR if done else 0
    return {
        "open": len(open_t),
        "critical": sum(1 for t in open_t if t["safety_risk"] or t["severity"] >= 4),
        "breaches": sum(1 for t in open_t if sla_left_hours(t) < 0),
        "avg_resolution_h": avg,
        "merged": sum(t.get("reports", 1) - 1 for t in tickets),
    }
