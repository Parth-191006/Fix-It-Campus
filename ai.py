"""Photo -> structured maintenance ticket, using Gemini multimodal.

If no GEMINI_API_KEY is set (or the call fails) we fall back to a small
keyword-based demo mode so the UI always works. The result says which
source produced it, so nothing is ever passed off as AI when it isn't.
"""
import json
import os

from pydantic import BaseModel, Field

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

CATEGORIES = [
    "Electrical", "Plumbing", "Furniture", "Civil/Structural", "HVAC/Cooling",
    "IT/Network", "Cleaning/Sanitation", "Safety Hazard", "Other",
]
TRADES = [
    "Electrician", "Plumber", "Carpenter", "Mason", "AC Technician",
    "IT Support", "Housekeeping", "Safety Officer", "General Maintenance",
]
DEFAULT_TRADE = {
    "Electrical": "Electrician", "Plumbing": "Plumber", "Furniture": "Carpenter",
    "Civil/Structural": "Mason", "HVAC/Cooling": "AC Technician",
    "IT/Network": "IT Support", "Cleaning/Sanitation": "Housekeeping",
    "Safety Hazard": "Safety Officer", "Other": "General Maintenance",
}


class Analysis(BaseModel):
    is_campus_issue: bool = Field(description="True if the photo shows something broken, damaged, unsafe or dirty that facilities could fix")
    category: str = Field(description=f"One of: {', '.join(CATEGORIES)}")
    issue: str = Field(description="Short title of the problem, max 8 words")
    severity: int = Field(description="1 (cosmetic) to 5 (immediate danger)")
    safety_risk: bool = Field(description="True if someone could get hurt if this is left alone")
    trade: str = Field(description=f"Who should fix it. One of: {', '.join(TRADES)}")
    est_fix_hours: float = Field(description="Rough hours of work needed")
    complaint_text: str = Field(description="2 clear sentences a maintenance supervisor can act on, mentioning what is visible")
    confidence: float = Field(description="0.0 to 1.0, how sure you are about this assessment")


PROMPT = """You are a facilities triage assistant for a college campus.
Look at the photo (and the optional note and location) and produce a maintenance ticket.

Severity guide:
5 = immediate danger (exposed live wiring, flooding near electrics, structural cracks, fire hazard, broken railing on stairs)
4 = high (no water/power in a busy area, serious leak, broken door lock on hostel)
3 = medium (functional problem that disrupts use: dead AC, leaking tap, broken projector)
2 = low (annoying but usable: flickering light, wobbly chair)
1 = cosmetic

Rules:
- Only describe what is actually visible. Do not invent details.
- If the photo does not show a repairable campus problem, set is_campus_issue to false.
- If unsure, lower the confidence rather than guessing.
- You assist a human supervisor; you do not diagnose root causes with certainty.
"""

KEYWORDS = [
    (["wire", "spark", "socket", "switch", "short"], "Electrical", 5, True),
    (["light", "bulb", "tube", "fan"], "Electrical", 2, False),
    (["leak", "tap", "pipe", "flood", "water", "drain", "toilet"], "Plumbing", 3, False),
    (["bench", "chair", "desk", "table", "door", "window"], "Furniture", 2, False),
    (["crack", "wall", "ceiling", "step", "stair", "plaster"], "Civil/Structural", 4, True),
    (["ac", "cooler", "cooling", "hot"], "HVAC/Cooling", 3, False),
    (["wifi", "network", "projector", "computer", "internet"], "IT/Network", 2, False),
    (["dirty", "garbage", "dustbin", "smell", "waste"], "Cleaning/Sanitation", 2, False),
]


def _clean(d: dict) -> dict:
    """Coerce model output into values the rest of the app can trust."""
    cat = d.get("category") if d.get("category") in CATEGORIES else "Other"
    trade = d.get("trade") if d.get("trade") in TRADES else DEFAULT_TRADE[cat]
    try:
        sev = max(1, min(5, int(d.get("severity", 3))))
    except (TypeError, ValueError):
        sev = 3
    safety = bool(d.get("safety_risk", False))
    if safety and sev < 4:
        sev = 4  # never under-rank something unsafe
    return {
        "is_campus_issue": bool(d.get("is_campus_issue", True)),
        "category": cat,
        "issue": str(d.get("issue", "Needs inspection"))[:80],
        "severity": sev,
        "safety_risk": safety,
        "trade": trade,
        "est_fix_hours": float(d.get("est_fix_hours", 2) or 2),
        "complaint_text": str(d.get("complaint_text", "")),
        "confidence": max(0.0, min(1.0, float(d.get("confidence", 0.5) or 0.5))),
    }


def _demo(note: str, location: str, reason: str) -> dict:
    text = f"{note} {location}".lower()
    cat, sev, safety = "Other", 3, False
    for words, c, s, sf in KEYWORDS:
        if any(w in text.split() or w in text for w in words):
            cat, sev, safety = c, s, sf
            break
    out = _clean({
        "is_campus_issue": True, "category": cat,
        "issue": (note.strip().capitalize()[:60] or "Needs inspection"),
        "severity": sev, "safety_risk": safety,
        "est_fix_hours": 2,
        "complaint_text": f"Reported at {location}. {note.strip() or 'No description given.'} Needs on-site inspection.",
        "confidence": 0.3,
    })
    out["source"] = f"demo mode ({reason})"
    return out


def gemini_enabled() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
                or os.getenv("GOOGLE_GENAI_USE_VERTEXAI"))


def analyze_photo(image_bytes: bytes, mime: str, note: str, location: str) -> dict:
    if not gemini_enabled():
        return _demo(note, location, "no API key set")
    try:
        from google import genai
        from google.genai import types

        client = genai.Client()  # reads GEMINI_API_KEY / GOOGLE_API_KEY / Vertex env vars
        context = f"{PROMPT}\nLocation: {location}\nStudent note: {note or '(none)'}"
        resp = client.models.generate_content(
            model=MODEL,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime), context],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=Analysis,
                temperature=0.2,
            ),
        )
        data = resp.parsed.model_dump() if resp.parsed else json.loads(resp.text)
        out = _clean(data)
        out["source"] = f"Gemini ({MODEL})"
        return out
    except Exception as e:  # network, quota, bad key, bad JSON...
        return _demo(note, location, f"Gemini call failed: {type(e).__name__}")
