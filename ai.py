"""Photo -> structured maintenance ticket, using Gemini multimodal.

If no GEMINI_API_KEY is set (or the call fails) we fall back to a small
keyword-based demo mode so the UI always works. The result says which
source produced it, so nothing is ever passed off as AI when it isn't.
"""
import json
import os

from pydantic import BaseModel, Field

# Model preference order. Google retired gemini-2.5-flash for new API keys: it
# still appears in ListModels, then returns 404 on generateContent. The bigger
# flash models also reject new keys with 503/429 spikes, so we lead with a model
# verified to be serving and keep the rest as fallbacks for when they recover.
# flash-lite handles this structured-extraction task well and answers in ~5s;
# override with GEMINI_MODEL (comma-separate to supply your own chain).
DEFAULT_MODELS = (
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite-preview",
)


def model_chain() -> tuple[str, ...]:
    override = tuple(m.strip() for m in os.getenv("GEMINI_MODEL", "").split(",") if m.strip())
    return override or DEFAULT_MODELS


# The model that last answered, so repeat requests skip the search.
_working_model: str | None = None


def active_model() -> str | None:
    """The model that last answered, if any. The UI shows this."""
    return _working_model

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


def api_key() -> str | None:
    """The API key, from the environment or from Streamlit secrets.

    Streamlit Cloud exposes root-level secrets as environment variables, but
    secrets set this way locally (a gitignored .streamlit/secrets.toml) only
    land in st.secrets, so check both and never depend on one.
    """
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.getenv(name):
            return os.getenv(name)
    try:
        import streamlit as st

        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            if name in st.secrets:
                return str(st.secrets[name])
    except Exception:
        pass  # no Streamlit, no secrets file, or malformed TOML
    return None


def gemini_enabled() -> bool:
    return bool(api_key() or os.getenv("GOOGLE_GENAI_USE_VERTEXAI"))


def _brief(exc: Exception) -> str:
    """Turn a client exception into one line worth showing to a human."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    text = " ".join(str(exc).split())[:160]
    return f"{type(exc).__name__}{f' {code}' if code else ''}" + (f" — {text}" if text else "")


def analyze_photo(image_bytes: bytes, mime: str, note: str, location: str) -> dict:
    global _working_model

    key = api_key()
    if not gemini_enabled():
        return _demo(note, location, "no API key set")
    try:
        from google import genai
        from google.genai import types
    except Exception as e:
        return _demo(note, location, f"google-genai not importable ({type(e).__name__})")

    # The SDK retries 503s with exponential backoff, which made a cold call take
    # ~27s while it ground through overloaded models. We do our own fallback, so
    # turn its retry off and let each attempt fail fast instead.
    http_options = types.HttpOptions(
        timeout=60_000,  # ms, per request
        retry_options=types.HttpRetryOptions(attempts=1),
    )
    client = genai.Client(api_key=key, http_options=http_options) if key \
        else genai.Client(http_options=http_options)
    context = f"{PROMPT}\nLocation: {location}\nStudent note: {note or '(none)'}"

    # Try the known-good model first, then the rest of the chain.
    chain = model_chain()
    order = ((_working_model,) if _working_model else ()) + tuple(m for m in chain if m != _working_model)

    failures = []
    for model in order:
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime), context],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Analysis,
                    temperature=0.2,
                ),
            )
            data = resp.parsed.model_dump() if resp.parsed else json.loads(resp.text)
            out = _clean(data)
            out["source"] = f"Gemini ({model})"
            _working_model = model
            return out
        except Exception as e:  # retired model, overload, quota, bad JSON...
            failures.append(f"{model}: {_brief(e)}")

    # One cause is usually behind every failure, so lead with the first and just
    # note how many models were tried rather than pasting the whole pile.
    summary = failures[0] if failures else "no models configured"
    if len(failures) > 1:
        summary += f" (+{len(failures) - 1} more model{'s' if len(failures) > 2 else ''})"
    return _demo(note, location, f"all Gemini models failed: {summary[:150]}")
