"""
LangGraph-based task decomposer for the orchestrator.

Graph structure:
  [START] → plan → execute → synthesize → [END]
               ↑_______________|
               (loop if plan decides more agents needed)

State:
  - user_query: original request
  - available_agents: list from registry (name, url, skills)
  - plan: list of AgentCall specs Gemini decided to make
  - completed_calls: results from executed agent calls
  - final_answer: synthesized response
  - iteration: safety counter (max 5 loops)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from orchestrator.a2a_client import A2AClientError, A2ATaskError, OrchestratorA2AClient
from shared.config import settings

log = structlog.get_logger(__name__)

MAX_ITERATIONS = 5


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class AgentCallSpec(TypedDict):
    """One planned agent invocation."""
    agent_name: str
    agent_url: str
    message: str
    reason: str


class AgentCallResult(TypedDict):
    """Result from one completed agent invocation."""
    agent_name: str
    agent_url: str
    message: str
    result: str
    success: bool
    error: str


class OrchestratorState(TypedDict):
    """Full state passed between LangGraph nodes."""
    user_query: str
    available_agents: list[dict]
    plan: list[AgentCallSpec]
    completed_calls: list[AgentCallResult]
    final_answer: str
    iteration: int
    error: str


# ---------------------------------------------------------------------------
# Gemini planner
# ---------------------------------------------------------------------------

async def _call_gemini_plan(
    query: str,
    available_agents: list[dict],
    completed_calls: list[AgentCallResult],
    iteration: int,
) -> list[AgentCallSpec]:
    """
    Ask Gemini which agents to call next.
    Returns list of AgentCallSpec. Empty list means "ready to synthesize".
    """
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=settings.google_api_key)

    agent_catalog = "\n".join([
        f"- {a['name']} at {a['url']}\n"
        f"  Description: {a.get('description', 'No description')}\n"
        f"  Skills: {', '.join(a.get('skills', []))}"
        for a in available_agents
    ])

    if completed_calls:
        completed_str = "\n\n".join([
            f"[{c['agent_name']}] Asked: {c['message']}\n"
            f"Result: {c['result'][:500]}{'...' if len(c['result']) > 500 else ''}"
            if c["success"] else
            f"[{c['agent_name']}] Asked: {c['message']}\nFAILED: {c['error']}"
            for c in completed_calls
        ])
    else:
        completed_str = "None yet."

    prompt = f"""You are an orchestrator deciding which AI agents to call to answer a user query.

USER QUERY: {query}

AVAILABLE AGENTS:
{agent_catalog}

WORK COMPLETED SO FAR (iteration {iteration}):
{completed_str}

TASK: Decide what to do next.

If you have enough information to answer the query fully, respond with:
DONE

If you need to call agents, respond with a JSON array of agent calls:
[
  {{
    "agent_name": "exact agent name from catalog",
    "agent_url": "exact URL from catalog",
    "message": "specific task description for this agent",
    "reason": "why this agent is needed"
  }}
]

Rules:
- Only call agents that are in the AVAILABLE AGENTS list
- Be specific in 'message' — the agent only sees your message, not the user query
- Don't repeat calls that already succeeded
- If a call failed, you may retry with a different approach
- Prefer parallel-compatible calls (call multiple agents if they don't depend on each other)
- Maximum {MAX_ITERATIONS} iterations total — you are on iteration {iteration}
- If on iteration {MAX_ITERATIONS}, respond DONE regardless

Respond with ONLY the JSON array or the word DONE. No other text."""

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=settings.orchestrator_model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(temperature=0.1),
    )

    text = (response.text or "").strip()
    log.info("planner_response", iteration=iteration, preview=text[:200])

    if text.upper() == "DONE" or not text:
        return []

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(l for l in lines if not l.startswith("```"))

    try:
        raw = json.loads(text)
        specs: list[AgentCallSpec] = []
        for item in raw:
            if "agent_url" not in item or "message" not in item:
                log.warning("planner_invalid_spec", item=item)
                continue
            specs.append(AgentCallSpec(
                agent_name=item.get("agent_name", "unknown"),
                agent_url=item["agent_url"],
                message=item["message"],
                reason=item.get("reason", ""),
            ))
        return specs
    except json.JSONDecodeError as e:
        log.warning("planner_json_parse_error", error=str(e), text=text[:300])
        return []


async def _call_gemini_synthesize(
    query: str,
    completed_calls: list[AgentCallResult],
) -> str:
    """Synthesize a final answer from all agent results."""
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=settings.google_api_key)

    if not completed_calls:
        return "I was unable to gather information to answer your query."

    results_str = "\n\n---\n\n".join([
        f"From {c['agent_name']} (asked: {c['message']}):\n{c['result']}"
        if c["success"] else
        f"From {c['agent_name']}: FAILED — {c['error']}"
        for c in completed_calls
    ])

    prompt = (
        f"A user asked: {query}\n\n"
        f"Here are the results gathered from specialized agents:\n\n"
        f"{results_str}\n\n"
        f"Please synthesize a clear, comprehensive answer to the user's query "
        f"using the agent results above. "
        f"Cite which agent provided which information. "
        f"If some agents failed, work with what's available."
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=settings.orchestrator_model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(temperature=0.2),
    )

    return response.text or "Synthesis failed — no response from model."


# ---------------------------------------------------------------------------
# LangGraph nodes
# ---------------------------------------------------------------------------

async def plan_node(state: OrchestratorState) -> dict:
    """Ask Gemini which agents to call next."""
    iteration = state["iteration"] + 1
    log.info("orchestrator_plan_node", iteration=iteration)

    if iteration > MAX_ITERATIONS:
        log.warning("orchestrator_max_iterations_reached")
        return {"plan": [], "iteration": iteration}

    try:
        plan = await _call_gemini_plan(
            query=state["user_query"],
            available_agents=state["available_agents"],
            completed_calls=state["completed_calls"],
            iteration=iteration,
        )
        return {"plan": plan, "iteration": iteration}
    except Exception as e:
        log.exception("plan_node_error")
        return {"plan": [], "iteration": iteration, "error": str(e)}


async def execute_node(state: OrchestratorState) -> dict:
    """Execute all planned agent calls concurrently."""
    plan = state["plan"]
    log.info("orchestrator_execute_node", call_count=len(plan))

    if not plan:
        return {"completed_calls": state["completed_calls"]}

    async def _call_one(spec: AgentCallSpec) -> AgentCallResult:
        log.info(
            "orchestrator_calling_agent",
            agent=spec["agent_name"],
            message_preview=spec["message"][:60],
        )
        try:
            async with OrchestratorA2AClient() as client:
                task = await client.send_task(
                    agent_url=spec["agent_url"],
                    message=spec["message"],
                )
                result_text = OrchestratorA2AClient.extract_text_result(task)
                return AgentCallResult(
                    agent_name=spec["agent_name"],
                    agent_url=spec["agent_url"],
                    message=spec["message"],
                    result=result_text,
                    success=True,
                    error="",
                )
        except A2ATaskError as e:
            result_text = OrchestratorA2AClient.extract_text_result(e.task)
            return AgentCallResult(
                agent_name=spec["agent_name"],
                agent_url=spec["agent_url"],
                message=spec["message"],
                result=result_text,
                success=False,
                error=str(e),
            )
        except A2AClientError as e:
            return AgentCallResult(
                agent_name=spec["agent_name"],
                agent_url=spec["agent_url"],
                message=spec["message"],
                result="",
                success=False,
                error=str(e),
            )

    new_results = await asyncio.gather(*[_call_one(spec) for spec in plan])

    all_results = list(state["completed_calls"]) + list(new_results)

    log.info(
        "orchestrator_execute_done",
        new=len(new_results),
        total=len(all_results),
        successes=sum(1 for r in new_results if r["success"]),
    )

    return {"completed_calls": all_results}


async def synthesize_node(state: OrchestratorState) -> dict:
    """Ask Gemini to synthesize a final answer from all agent results."""
    log.info(
        "orchestrator_synthesize_node",
        results_count=len(state["completed_calls"]),
    )
    try:
        answer = await _call_gemini_synthesize(
            query=state["user_query"],
            completed_calls=state["completed_calls"],
        )
        return {"final_answer": answer}
    except Exception as e:
        log.exception("synthesize_node_error")
        return {"final_answer": f"Synthesis error: {e}"}


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

def should_continue(state: OrchestratorState) -> str:
    """After execute_node: plan again or synthesize."""
    if not state["plan"]:
        return "synthesize"
    return "plan"


def after_plan(state: OrchestratorState) -> str:
    """After plan_node: execute if work to do, synthesize if done."""
    if state["plan"]:
        return "execute"
    return "synthesize"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_orchestrator_graph() -> Any:
    """
    Build and compile the LangGraph orchestrator graph.

    Graph: START → plan → [execute → plan]* → synthesize → END
    """
    graph = StateGraph(OrchestratorState)

    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("synthesize", synthesize_node)

    graph.add_edge(START, "plan")

    graph.add_conditional_edges(
        "plan",
        after_plan,
        {"execute": "execute", "synthesize": "synthesize"},
    )

    graph.add_conditional_edges(
        "execute",
        should_continue,
        {"plan": "plan", "synthesize": "synthesize"},
    )

    graph.add_edge("synthesize", END)

    return graph.compile()


orchestrator_graph = build_orchestrator_graph()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_orchestrator(
    query: str,
    available_agents: list[dict],
) -> tuple[str, list[AgentCallResult]]:
    """
    Run the full orchestrator graph for a user query.

    Returns:
        (final_answer, completed_calls) tuple
    """
    initial_state = OrchestratorState(
        user_query=query,
        available_agents=available_agents,
        plan=[],
        completed_calls=[],
        final_answer="",
        iteration=0,
        error="",
    )

    log.info(
        "orchestrator_run_start",
        query_preview=query[:80],
        agents=len(available_agents),
    )

    final_state = await orchestrator_graph.ainvoke(initial_state)

    log.info(
        "orchestrator_run_complete",
        iterations=final_state["iteration"],
        calls_made=len(final_state["completed_calls"]),
        answer_length=len(final_state["final_answer"]),
    )

    return final_state["final_answer"], final_state["completed_calls"]