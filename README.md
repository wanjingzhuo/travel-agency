# AI Travel Planner

A multi-agent trip recommendation system. Give it your dates, group size, budget, and preferred regions, and a crew of AI agents researches each region in parallel, then a supervisor agent picks the single best itinerary and explains why.

## How it works

- **Region researchers** (1-4, one per selected region) run concurrently, each searching the web for seasonal weather and typical flight/hotel prices, then proposing a complete day-by-day itinerary for its region.
- A **supervisor** agent waits for all of them, compares the proposals on climate fit, budget fit, and overall value, and returns one final recommendation.
- Every agent's steps (tool calls, reasoning, final output) are recorded and viewable in a **Decision Log**, so the AI's decision process isn't a black box.

This is a **Parallel Fan-out** architecture (CrewAI's `async_execution=True` tasks fanning in via `context=[...]`), not a hierarchical/manager pattern - the set of possible regions is fixed and known upfront, so there's no need for a manager LLM to dynamically decide who to call.

## Tech stack

- **Backend:** Python, FastAPI, CrewAI, Google Gemini (via CrewAI's LLM interface), Serper (web search)
- **Frontend:** Plain HTML/CSS/JavaScript - no framework, no build step
- **Deployment:** Frontend on Vercel, backend on Render

## Project structure

```
travel-planner/
├── backend/
│   ├── main.py          # FastAPI app: POST /api/plan-trip, GET /api/trace/{run_id}
│   ├── crew.py           # Agent/task/crew definitions (the core architecture)
│   ├── models.py         # Pydantic request/response models + validation
│   ├── regions.py        # Shared list of valid regions
│   └── trace_store.py     # In-memory run_id -> {recommendation, trace} store
├── frontend/
│   ├── index.html         # Plan a Trip / Decision Log tabs
│   ├── app.js             # Form handling, custom date/region pickers, trace rendering
│   └── style.css
└── requirements.txt
render.yaml                 # Render Blueprint config for the backend
```

## Running locally

```bash
cd travel-planner
pip install -r requirements.txt
cp backend/.env.example backend/.env   # then fill in your API keys
uvicorn --app-dir backend main:app --reload
```

Open `http://localhost:8000` - the backend serves the frontend directly for local dev, so no separate frontend server is needed.

You'll need:
- `GEMINI_API_KEY` - from [Google AI Studio](https://aistudio.google.com/)
- `SERPER_API_KEY` - from [serper.dev](https://serper.dev/)

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/plan-trip` | POST | Takes trip details + selected regions, runs the crew, returns a recommendation |
| `/api/trace/{run_id}` | GET | Returns the full step-by-step agent trace for a completed run |

## Deployment

The frontend and backend are deployed separately:

- **Frontend (Vercel):** static site, root directory `travel-planner/frontend`, no build step.
- **Backend (Render):** deployed via the `render.yaml` Blueprint at the repo root. Set `GEMINI_API_KEY` and `SERPER_API_KEY` as environment variables in the Render dashboard (not committed to git). Optionally set `FRONTEND_ORIGIN` to your Vercel URL to lock down CORS.

If you rename the Render service, update the hardcoded API URL in `travel-planner/frontend/app.js` and redeploy the frontend.

## Known limitations

- **Gemini free-tier rate limits.** The crew's LLM calls are throttled client-side (`max_rpm` in `crew.py`) to avoid crashing on 429s, but this means a run can take several minutes rather than the ~1-2 minutes you'd see on a paid tier.
- **No persistence.** Run results and traces live in an in-memory dict (`trace_store.py`) - they're lost on server restart, and there are no user accounts or run history. This is an intentional MVP scope choice, not an oversight.
