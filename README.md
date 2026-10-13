# FixIt Campus

Snap a photo of anything broken on campus. Gemini works out what it is, how urgent it is and who should fix it, then routes a ticket to the right maintenance team.

**Google services:** Gemini API (multimodal triage) · Cloud Run (hosting) · Firestore (tickets, optional)

## Run locally (5 lines)

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=your-key-from-aistudio.google.com   # optional: without it the app runs in demo mode
streamlit run app.py
```

Use the sidebar to switch between **Student**, **Maintenance** and **Admin** views.

## Deploy to Cloud Run

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud run deploy fixit-campus --source . --region asia-south1 --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=your-key,USE_FIRESTORE=1
```

For `USE_FIRESTORE=1`, enable Firestore (Native mode) in the project once. Cloud Run's default service account needs the "Cloud Datastore User" role. Leave it off to use a local JSON file (data resets when the container restarts).

## How it works

1. Student takes a photo and picks a location. `ai.py` sends the image to Gemini with a JSON schema and gets back category, severity, safety risk, trade and a ready-to-act description.
2. Output is validated in code: unknown categories fall back to "Other", and anything flagged as a safety risk is never ranked below High.
3. `store.py` checks for an open ticket with the same location and category. If one exists, the new report is merged into it instead of creating a duplicate.
4. The maintenance queue sorts by safety risk, severity, number of reports, then age, and tracks time left against an SLA based on severity.
5. The admin view shows open and critical tickets, SLA breaches, average fix time and problem hotspots.

## What is live vs. mocked

| Part | Status |
|---|---|
| Photo to ticket with Gemini | Live when `GEMINI_API_KEY` is set. Otherwise a keyword-based demo mode, labelled as such in the UI |
| Ticket queue, duplicate merge, SLA tracking | Live |
| Firestore storage | Live when `USE_FIRESTORE=1` |
| Seed tickets (9 starter tickets) | Sample data. Edit `_seed()` in `store.py` |
| Login / roles | Not built. Role switch is a sidebar toggle |
| Push notifications, maps, analytics | Roadmap (see deck) |

## Files

`app.py` UI · `ai.py` Gemini triage · `store.py` storage and ticket logic · `test_smoke.py` quick checks
