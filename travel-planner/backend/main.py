"""FastAPI app: POST /api/plan-trip and GET /api/trace/{run_id}."""

import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from crew import build_crew
from models import PlanTripResponse, Recommendation, TraceResponse, TripRequest
from trace_store import get_run, new_run_id, save_run

logger = logging.getLogger("travel_planner")
logging.basicConfig(level=logging.INFO)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# Deployed separately (frontend on Vercel, this API on Render), so the two
# live on different origins. Defaults to "*" for local/same-origin dev; set
# FRONTEND_ORIGIN to the Vercel URL in production to lock CORS down to it.
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")

app = FastAPI(title="AI Travel Planner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)


def extract_json(raw: str) -> dict:
    """Best-effort JSON extraction from an LLM's raw text output.

    LLMs often wrap JSON in ```json fences or add stray prose around it.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


@app.post("/api/plan-trip", response_model=PlanTripResponse)
def plan_trip(trip: TripRequest) -> PlanTripResponse:
    trip_dict = {
        "start_date": trip.start_date.isoformat(),
        "end_date": trip.end_date.isoformat(),
        "travelers": trip.travelers,
        "budget_per_person": trip.budget_per_person,
        "currency": trip.currency,
    }

    trace_log: list[dict] = []
    crew = build_crew(trip_dict, trace_log, regions=trip.regions)

    try:
        result = crew.kickoff(inputs=trip_dict)
    except Exception:
        logger.exception("Crew run failed")
        raise HTTPException(
            status_code=502, detail="Trip planning crew failed to complete."
        )

    try:
        recommendation = Recommendation(**extract_json(result.raw))
    except Exception:
        logger.exception("Could not parse supervisor output as structured JSON")
        recommendation = Recommendation(
            recommended_region="unknown",
            destination="unknown",
            reasoning=result.raw,
        )

    run_id = new_run_id()
    save_run(run_id, recommendation.model_dump(), trace_log)

    return PlanTripResponse(run_id=run_id, recommendation=recommendation)


@app.get("/api/trace/{run_id}", response_model=TraceResponse)
def get_trace(run_id: str) -> TraceResponse:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return TraceResponse(run_id=run_id, trace=run["trace"])


# Serve the plain HTML/JS frontend. Mounted last so it never shadows /api routes.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
