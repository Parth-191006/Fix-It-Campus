# FixIt Campus

Snap a photo of anything broken on campus. Gemini works out what it is, how urgent it is and who should fix it, then routes a ticket to the right maintenance team.

**Live:** https://fix-it-campus.streamlit.app · **Repo:** https://github.com/Parth-191006/Fix-It-Campus

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| UI | **Streamlit 1.65** (Python) | One file of Python becomes a real app; no JS build step to babysit during a hackathon |
| Design layer | `ui.py` + `.streamlit/config.toml` | Custom CSS, theme tokens and small HTML components (`chip`, `meter`, `hero`) in one place |
| AI triage | **Gemini via `google-genai`**, multimodal | Photo → typed JSON (`category`, `severity`, `safety_risk`, `trade`, `description`) in one call |
| Output contract | **Pydantic** `response_schema` | The model is forced into a schema, then re-validated in `_clean()` before anything trusts it |
| Images | **Pillow** | Downscales every photo to a ~480px JPEG thumbnail before storage |
| Data | JSON file, or **Firestore** | Local file for zero-setup demos, Firestore when `USE_FIRESTORE=1` |
| Tables/charts | **pandas** + Streamlit charts | Hotspots by location and breakdown by category |
| Hosting | **Streamlit Community Cloud** | Free, HTTPS, auto-redeploys on push to `main` |

Everything runs on one Python process — no queue, no worker, no database required to demo.

## How it works

1. Student takes or uploads a photo and picks a location. `ai.py` sends the image to Gemini with a JSON schema and gets back category, severity, safety risk, trade and a ready-to-act description.
2. Output is validated in code: unknown categories fall back to `"Other"`, and anything flagged as a safety risk is never ranked below High.
3. `store.py` checks for an open ticket with the same location and category. If one exists, the new report is merged into it instead of creating a duplicate.
4. The maintenance queue sorts by safety risk, severity, number of reports, then age — and shows a meter for time left against an SLA based on severity.
5. The admin view shows open and critical tickets, SLA breaches, average fix time and problem hotspots.

## Gemini model handling

Google **retired `gemini-2.5-flash` for new API keys** — it still shows up in `ListModels`, then returns `404` on `generateContent`. Newer models also reject new keys with `503`/`429` while a region is loaded. So `ai.py` does not hardcode one model:

- `DEFAULT_MODELS` is a priority chain (`gemini-3.1-flash-lite` first, then larger flash models as fallbacks).
- The app walks the chain until one answers and **remembers the winner** for the rest of the process.
- The SDK's own retry is disabled (`HttpRetryOptions(attempts=1)`) so an overloaded model fails fast instead of burning ~10s in backoff. Measured: a cold call went from **27.1s to 4.3s**, warm **5.1s to 3.6s**.
- If every model fails, the reason is surfaced in the UI verbatim (e.g. *"API key not valid"*) — it is never passed off as AI output.

Override the chain with a comma-separated `GEMINI_MODEL`, e.g. `GEMINI_MODEL=gemini-3.5-flash,gemini-flash-latest`.

## Run locally

```bash
pip install -r requirements.txt
echo 'GEMINI_API_KEY = "your-key-from-aistudio.google.com"' > .streamlit/secrets.toml   # optional
streamlit run app.py
```

Without a key the app runs in **keyword demo mode** and says so in the UI. The key is read from `GEMINI_API_KEY` **or** `GOOGLE_API_KEY`, from either the environment or `.streamlit/secrets.toml` (both are gitignored). Use the sidebar to switch between **Student**, **Maintenance** and **Admin**.

## Deploy

Streamlit Community Cloud (current): push to `main`, then **Create app → Deploy a public app from GitHub**, repo `Fix-It-Campus`, branch `main`, main file `app.py`, and paste secrets into **Manage app → Settings → Secrets** as a root-level key:

```toml
GEMINI_API_KEY = "your-key"
```

Keep it at the root, not under a `[section]` header — section values do not become environment variables.

<details>
<summary>Alternative: Cloud Run (needs billing enabled)</summary>

```bash
gcloud run deploy fixit-campus --source . --region asia-south1 --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=your-key,USE_FIRESTORE=1
```

</details>

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `GEMINI_API_KEY` | — | Turns on Gemini triage; absent means demo mode |
| `GEMINI_MODEL` | built-in chain | Comma-separated model preference list |
| `USE_FIRESTORE` | `0` | `1` stores tickets in Firestore instead of a JSON file |
| `DATA_DIR` | `data` | Where the JSON store lives (the container uses `/tmp/data`) |

## What is live vs. mocked

| Part | Status |
|---|---|
| Photo to ticket with Gemini | **Live** — verified end to end, including submit and persistence |
| Ticket queue, duplicate merge, SLA tracking | **Live** |
| Custom UI (theme, chips, SLA meters, cards) | **Live** |
| Firestore storage | Live when `USE_FIRESTORE=1` |
| Seed tickets (9 starter tickets) | Sample data. Edit `_seed()` in `store.py` |
| Login / roles | Not built. Role switch is a sidebar toggle |
| Push notifications, maps, analytics | Roadmap |

## Known limitations

- Tickets are stored in a JSON file on the container, so **data resets when the app sleeps or redeploys** (it re-seeds, so it never looks empty). Firestore fixes this but needs billing.
- The nine seed tickets have no photos, so their cards show a 🔧 placeholder.
- `st.camera_input` needs browser camera permission, which is only offered over HTTPS — fine on the live URL.

## Files

`app.py` UI and flows · `ui.py` theme, CSS and components · `ai.py` Gemini triage and model chain · `store.py` storage, ticket logic and SLA · `test_smoke.py` quick checks · `.streamlit/config.toml` theme
