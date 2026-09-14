"""Agent/task/crew definitions for the AI Travel Planner.

Architecture: Parallel Fan-out (1-4 region researchers, picked by the client,
running with async_execution=True) + a Synthesizer task that fans-in via
context=[...]. Not Process.hierarchical: the set of possible regions is
fixed and known upfront, so there is no need for a manager LLM to dynamically
decide who to call - the client just decides which subset to run.
"""

from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from crewai import LLM, Agent, Crew, Process, Task
from crewai.agents.parser import AgentAction, AgentFinish
from crewai_tools import SerperDevTool

from regions import REGIONS

SUPERVISOR_ROLE = "Trip Supervisor"
GEMINI_MODEL = "gemini/gemini-3.1-flash-lite"
# Gemini free tier caps this key at 5 requests/min. With several researchers
# running in parallel, an unthrottled crew blows through that in seconds and
# every agent gets 429 RESOURCE_EXHAUSTED. Crew(max_rpm=...) makes every agent
# share one client-side limiter that waits for a free slot instead of firing
# all at once, so the run finishes rather than crashing (at the cost of taking
# longer than the free-tier-less estimate).
MAX_RPM = 4

search_tool = SerperDevTool()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_llm() -> LLM:
    return LLM(model=GEMINI_MODEL, temperature=0.4)


def make_researcher(region: str) -> Agent:
    return Agent(
        role=f"{region} Travel Researcher",
        goal=(
            f"Find the single best itinerary in {region} for the given dates, "
            f"traveler count, and per-person budget. Consider seasonal weather/climate "
            f"suitability, and realistic price estimates (flights + hotels + activities)."
        ),
        backstory=(
            f"A travel specialist who has planned hundreds of {region} trips. "
            f"Sceptical of generic recommendations - always checks actual seasonal "
            f"conditions for the specific travel dates before suggesting a destination."
        ),
        tools=[search_tool],
        llm=make_llm(),
        verbose=True,
    )


def make_research_task(agent: Agent, region: str, trip: dict) -> Task:
    return Task(
        description=(
            f"Research {region} and propose ONE best itinerary for a trip with:\n"
            f"- Dates: {trip['start_date']} to {trip['end_date']}\n"
            f"- Travelers: {trip['travelers']}\n"
            f"- Budget: {trip['budget_per_person']} {trip['currency']} per person\n\n"
            f"Search for: seasonal weather/climate at the travel dates, typical flight "
            f"and hotel prices for that period, and 1-2 destination candidates within "
            f"{region} that best fit the season and budget. Pick ONE final destination "
            f"and build a day-by-day itinerary.\n\n"
            f"Edge cases you must handle:\n"
            f"- If a search fails or returns nothing useful, fall back to your own "
            f"knowledge, give a conservative estimate, and note in the output that "
            f"the data is limited/estimated.\n"
            f"- If the budget is clearly unrealistic for this region, say so honestly "
            f"and propose the most economical option instead of inventing numbers.\n"
            f"- Judge season by the real travel dates AND hemisphere (e.g. December is "
            f"dry season in Southeast Asia but summer in New Zealand) - never assume "
            f"season from month alone."
        ),
        expected_output=(
            "A JSON object with fields: region, destination_city_country, "
            "climate_summary, estimated_total_cost_per_person, budget_fit "
            "('under'/'on_target'/'over'), day_by_day_itinerary (list of "
            "{day, activities}), and a 2-3 sentence rationale for why this is "
            "the best pick in this region for these dates."
        ),
        agent=agent,
        async_execution=True,
    )


def make_supervisor() -> Agent:
    return Agent(
        role=SUPERVISOR_ROLE,
        goal=(
            "Compare the regional itinerary proposals and select the single best "
            "one for the client, considering climate fit, budget fit, and overall value."
        ),
        backstory=(
            "A senior travel consultant who makes the final call across all regions. "
            "Rejects a proposal if it clearly overshoots budget or has bad seasonal timing, "
            "prefers the next-best option in that case."
        ),
        llm=make_llm(),
        verbose=True,
    )


def make_final_task(supervisor: Agent, region_tasks: list[Task], selected_regions: list[str]) -> Task:
    region_list = ", ".join(selected_regions)
    return Task(
        description=(
            f"You have {len(selected_regions)} regional itinerary proposal(s) ({region_list}) "
            "as context. Compare them on: (1) climate/season suitability, (2) budget fit "
            "against the per-person budget, (3) overall value/experience. Pick the single "
            "best one. If the top choice is over budget by more than 15% and a better-fitting "
            "alternative exists among the proposals, pick that instead and say why."
        ),
        expected_output=(
            "A JSON object: {recommended_region, destination, reasoning (why this beat "
            "the other proposal(s), referencing each briefly), itinerary (from the winning "
            "researcher, unchanged), estimated_total_cost_per_person, region_summaries "
            "(one-line verdict per proposed region, including why any non-winning ones "
            "were not chosen)}."
        ),
        agent=supervisor,
        context=region_tasks,
    )


def _serialize_step(agent_role: str, step: object) -> dict:
    """Normalize a crewai AgentAction/AgentFinish into a JSON-safe trace event.

    Neither dataclass carries the agent's identity, so the caller must supply
    it (via a per-agent step_callback closure) rather than reading it off the step.
    """
    event = {"type": "step", "agent": agent_role, "timestamp": utc_now_iso()}
    if isinstance(step, AgentAction):
        event["thought"] = step.thought
        event["tool"] = step.tool
        event["tool_input"] = step.tool_input
    elif isinstance(step, AgentFinish):
        output = step.output
        event["thought"] = step.thought
        event["output"] = output if isinstance(output, str) else str(output)
    else:
        event["thought"] = str(step)
    return event


def build_crew(trip: dict, trace_log: list[dict], regions: list[str] | None = None) -> Crew:
    """Build the crew for a given trip request dict.

    trip must have: start_date, end_date, travelers, budget_per_person, currency.
    regions selects which of REGIONS to spin up a researcher for (defaults to
    all of them); the client picks this subset to skip regions it doesn't
    care about instead of always paying for 4 parallel searches.
    trace_log is mutated in place as the crew runs (step + task_complete events).
    """
    selected_regions = regions or REGIONS

    def make_step_callback(agent_role: str):
        def _on_step(step: object) -> None:
            trace_log.append(_serialize_step(agent_role, step))

        return _on_step

    def _on_task_done(task_output) -> None:
        trace_log.append(
            {
                "type": "task_complete",
                "agent": task_output.agent,
                "output": task_output.raw,
                "timestamp": utc_now_iso(),
            }
        )

    researchers = {}
    for region in selected_regions:
        agent = make_researcher(region)
        agent.step_callback = make_step_callback(agent.role)
        researchers[region] = agent

    region_tasks = [
        make_research_task(researchers[region], region, trip) for region in selected_regions
    ]

    supervisor = make_supervisor()
    supervisor.step_callback = make_step_callback(supervisor.role)
    final_task = make_final_task(supervisor, region_tasks, selected_regions)

    return Crew(
        agents=[*researchers.values(), supervisor],
        tasks=[*region_tasks, final_task],
        process=Process.sequential,
        task_callback=_on_task_done,
        max_rpm=MAX_RPM,
        verbose=True,
    )


if __name__ == "__main__":
    # Quick manual smoke test: run the whole crew from the command line with
    # fake trip data, no FastAPI involved. Confirms async_execution + the
    # context=[...] fan-in actually parallelize and actually wait for all four.
    fake_trip = {
        "start_date": "2026-12-10",
        "end_date": "2026-12-20",
        "travelers": 2,
        "budget_per_person": 2000,
        "currency": "USD",
    }

    trace_log: list[dict] = []
    crew = build_crew(fake_trip, trace_log)
    result = crew.kickoff(inputs=fake_trip)

    print("\n\n=== FINAL RESULT ===")
    print(result.raw)
    print(f"\n\n=== TRACE LOG ({len(trace_log)} events) ===")
    for event in trace_log:
        print(event)
