from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent #, UsageLimits
# from pydantic_ai.messages import ModelResponse, ModelRequest, ToolCallPart, ToolReturnPart
# from pydantic_ai.mcp import MCPToolset
# from mcp_server import mcp as financial_mcp_server
import json
import os
from prefect import flow, task
from prefect.cache_policies import INPUTS
from datetime import timedelta
import time

# initialize local FastMCP tools
# financial_tools = MCPToolset(financial_mcp_server)

# Secrets are injected as env vars by the Kubernetes worker (via K8s Secrets → pod env).
# OPENAI_API_KEY and COHERE_API_KEY must be present in the pod environment.

# --- MODELS ---

class PlanStep(BaseModel):
    step_id: int = Field(description="Sequential step number starting at 1.")
    tool_hint: Literal["query_nyse_market_data", "search_news_headlines", "both"] = Field(
        description="Which MCP tool(s) this step should primarily invoke."
    )
    instruction: str = Field(description="Concrete instruction for the tool-calling agent.")
    rationale: str = Field(description="Why this step is needed and what it contributes to the overall goal.")

class ExecutionPlan(BaseModel):
    reasoning: str = Field(description="High-level rationale for the chosen plan.")
    steps: list[PlanStep] = Field(description="Ordered steps to execute.")

class PlanRevision(BaseModel):
    revision_reasoning: str = Field(description="Assessment of the step result and what, if anything, needs to change.")
    status: Literal["continue", "complete", "blocked"] = Field(
        description="'complete' when intent is satisfied, 'blocked' when data is definitively unavailable, 'continue' otherwise."
    )
    revised_remaining_steps: list[PlanStep] | None = Field(
        default=None,
        description="Updated remaining steps if the plan needs adjustment. null to keep original remaining steps."
    )
    block_reason: str | None = Field(
        default=None,
        description="If blocked, explain which data is unavailable from the current tools."
    )

# --- AGENTS ---

agent = Agent(
    'openai:gpt-4o-mini',
    # toolsets=[financial_tools],
    retries=2,
    system_prompt=(
        "You are an expert production financial analyst assistant. You have access to "
        "NYSE market tables (fundamentals and historical prices) and a semantic vector database "
        "of financial news headlines.\n\n"
        "Your objective is to answer user queries comprehensively by executing read-only SQL "
        "statements or semantic keyword queries. \n"
        "CRITICAL SAFEGUARDS:\n"
        "1. Never attempt modification statements (INSERT/UPDATE/DELETE).\n"
        "2. If a SQL error or schema mismatch occurs, examine the available columns "
        "   provided in the tool description, correct your query syntax, and try again.\n"
        "3. Always cross-reference financial metrics from the NYSE data tables with historical "
        "   context retrieved from the news headline vector database to formulate a well-rounded response.\n"
        "4. If the available tools do not contain the requested metric or factual data, stop and "
        "   explicitly report that limitation instead of continuing to reformulate unsupported queries."
    )
)

planner_agent = Agent(
    'openai:gpt-4o-mini',
    output_type=ExecutionPlan,
    system_prompt=(
        "You are a financial research planner. Given a user's analytical intent, "
        "produce a minimal, ordered execution plan using only these available tools:\n"
        "  - query_nyse_market_data: executes read-only SQL against NYSE price and fundamentals tables\n"
        "  - search_news_headlines: semantic vector search over a financial news headline text\n\n"
        "Rules:\n"
        "1. Every step must map to one of the tools above (or 'both' if a step genuinely needs both).\n"
        "2. Sequence steps so earlier results meaningfully inform later ones.\n"
        "3. Keep the plan to the fewest steps necessary — avoid padding.\n"
        "4. If the intent cannot be addressed with these tools at all, produce a single step "
        "   explaining the limitation.\n"
        "5. Do NOT write SQL queries in the instructions. Describe the desired data or action in "
        "   plain language only — the execution agent has direct access to the tool schema and will "
        "   construct the correct query itself."
    )
)

adapter_agent = Agent(
    'openai:gpt-4o-mini',
    output_type=PlanRevision,
    system_prompt=(
        "You are a plan revision agent. After each executed step, evaluate the gathered context "
        "against the original intent and the remaining planned steps.\n\n"
        "Rules:\n"
        "1. Use 'complete' only when the context fully satisfies the intent — do not use it prematurely.\n"
        "2. Use 'blocked' when required data is definitively unavailable from the tools (schema gap, "
        "   missing data, or repeated tool failures) — do not keep retrying a blocked path.\n"
        "3. Use 'continue' when remaining steps are still useful; optionally revise them if the "
        "   step result revealed a better approach.\n"
        "4. Revised steps must only use: query_nyse_market_data, search_news_headlines, or both."
    )
)

# --- TASKS ---

# cache based on task arguments, the same (step_id, user_prompt, historical_context) will prevent skip the execution
@task(
    name="Agent Execution Step", 
    cache_policy=INPUTS, 
    cache_expiration=timedelta(minutes=10), # limit cache duration, same as the request timeout limit
    timeout_seconds=120
)
async def run_dynamic_agent_step(step_id: int, prompt: str, context: str):
    print(f"Executing Step {step_id}: instruction: {prompt} (Cache Miss)...")
        
    # # Execute step using the cumulative context built from prior loop steps
    # result = await agent.run(
    #     f"Context: {context}. Prompt: {prompt}", 
    #     usage_limits=UsageLimits(
    #     request_limit=4, # 1 tool selection, free tool action, 1 tool observation/interpretation
    #     total_tokens_limit = 6000 # additional threshold on top of the limitations placed on the mcp tool call (see mcp_server.py tools) buffer zone between the agent and tool calls
    # ))
    # for msg in result.all_messages():
    #     if isinstance(msg, ModelResponse):
    #         for part in msg.parts:
    #             if isinstance(part, ToolCallPart):
    #                 print(f"  [TOOL CALL] {part.tool_name}  args={part.args}")
    #     if isinstance(msg, ModelRequest):
    #         for part in msg.parts:
    #             if isinstance(part, ToolReturnPart):
    #                 print(f"  [TOOL RESULT] {part.tool_name}  → {part.content}")
    # return result.output
    time.sleep(2)
    return f"output of the execution {step_id}: Empty"

@task(name="Create Execution Plan", cache_policy=INPUTS, cache_expiration=timedelta(minutes=10))
async def create_execution_plan(intent: str, max_steps: int) -> ExecutionPlan:
    print("Creating execution plan...")
    result = await planner_agent.run(
        f"Intent: {intent}\n\nProduce a plan with at most {max_steps} steps."
    )
    plan = result.output
    print(f"Plan reasoning: {plan.reasoning}")
    for step in plan.steps:
        print(f"  Step {step.step_id} [{step.tool_hint}]: {step.instruction}")
    return plan

@task(name="Revise Execution Plan", cache_policy=INPUTS, cache_expiration=timedelta(minutes=10))
async def revise_execution_plan(intent: str, context: str, remaining_steps_json: str, step_id: int) -> PlanRevision:
    print(f"Revising plan after step {step_id}...")
    result = await adapter_agent.run(
        f"Intent: {intent}\n\nGathered Context:\n{context}\n\nRemaining Planned Steps (JSON):\n{remaining_steps_json}"
    )
    revision = result.output
    print(f"  Revision [{revision.status}]: {revision.revision_reasoning}")
    return revision

@task(name="Final Summarizer", cache_policy=INPUTS, cache_expiration=timedelta(minutes=10))
async def generate_final_summary(intent: str, full_context: str) -> str:
    print("Generating Final Summary Report...")
    summarizer = Agent('openai:gpt-4o-mini', system_prompt="Synthesize the gathered context into a clear, structured response. Only share information that is relevant to the original intent, without additional information.")
    result = await summarizer.run(f"Original Intent: {intent}\n\nGathered Data:\n{full_context}")
    return result.output

# --- PIPELINE ORCHESTRATION ---

@flow(
    name="resumable-pipeline",
    retries=5,
    retry_delay_seconds=10,
    timeout_seconds=300,
    log_prints=True,
    # result_storage is configured via PREFECT_RESULTS_DEFAULT_STORAGE_BLOCK env var
)
async def financial_react_pipeline(user_intent: str, max_tasks: int = 5):
    print(f"Starting Autonomous Pipeline for: '{user_intent}'")

    # Plan — planner sees both available tools and produces an ordered, tool-aware step list
    plan = await create_execution_plan(user_intent, max_tasks)
    remaining_steps: list[PlanStep] = list(plan.steps[:max_tasks])
    cumulative_context = "No data gathered yet."

    while remaining_steps:
        current_step = remaining_steps.pop(0)
        print(f"\n--- Step {current_step.step_id} [{current_step.tool_hint}] ---")
        print(f"   Rationale: {current_step.rationale}")

        # Act — tool hint is embedded in the prompt to guide tool selection
        step_result = await run_dynamic_agent_step(
            step_id=current_step.step_id,
            prompt=f"[Preferred tool: {current_step.tool_hint}] {current_step.instruction}",
            context=cumulative_context
        )
        cumulative_context += f"\n\n[Step {current_step.step_id} Result]:\n{step_result}"

        # If this was the last planned step, skip revision and move to summary
        if not remaining_steps:
            print("All planned steps completed.")
            break

        # Adapt - revise remaining plan based on what was just learned
        remaining_json = json.dumps([s.model_dump() for s in remaining_steps])
        revision = await revise_execution_plan(
            intent=user_intent,
            context=cumulative_context,
            remaining_steps_json=remaining_json,
            step_id=current_step.step_id
        )

        if revision.status == "complete":
            print("-- Intent satisfied early — skipping remaining steps.")
            break

        if revision.status == "blocked":
            reason = revision.block_reason or "Required data unavailable from current tools."
            print(f"-- Blocked: {reason}")
            cumulative_context += f"\n\n[Stop Condition]:\n{reason}"
            break

        # continue: use revised steps if provided, otherwise keep existing remaining steps
        if revision.revised_remaining_steps is not None:
            remaining_steps = revision.revised_remaining_steps
            print(f"-- Plan revised: {len(remaining_steps)} step(s) remaining.")

    # Summarize accumulated text
    final_output = await generate_final_summary(user_intent, cumulative_context)
    print("\n" + "="*40 + "\nFINAL OUTPUT\n" + "="*40)
    print(final_output)
    return final_output