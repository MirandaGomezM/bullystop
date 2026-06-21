"""
BullyStop ADK Agents

Multi-agent architecture built with Google Agent Development Kit (ADK).

Topology
--------
  orchestrator_agent            (reads [CONTEXT] header, routes immediately)
    ├── hearme_agent            ← students
    ├── parentguide_agent       ← parents / guardians
    └── protocol_agent          ← teachers / administrators

Each specialized agent exposes get_support_resources as a tool.  The Gradio demo
wires this as a direct Python FunctionTool (sync-compatible, zero overhead).  For an
async / production deployment the same agents can be rebuilt against the real MCP
server via create_agents_with_mcp() at the bottom of this file.

Usage (sync, Gradio path)
-------------------------
    from agents.bullystop_agents import run_adk, session_service
    session_service.create_session(app_name="bullystop", user_id=sid, session_id=sid)
    reply, tool_called = run_adk(role, severity, country, message, sid)

Usage (async, MCP path)
-----------------------
    orch, stack = await create_agents_with_mcp()
    runner = Runner(agent=orch, app_name="bullystop",
                    session_service=InMemorySessionService())
    # ... run turns ...
    await stack.aclose()
"""

import importlib.util
import json
import logging
import os
import re
import sys

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

# ── Package-level paths ────────────────────────────────────────────────────

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILLS_DIR = os.path.join(_PKG_ROOT, "skills")
_MCP_SERVER = os.path.join(_PKG_ROOT, "mcp_server.py")

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

# ── Skill-body loader (mirrors app.py — self-contained to avoid circular import) ──

_skill_cache: dict[str, str] = {}


def _load_skill_body(skill_dir: str) -> str:
    if skill_dir not in _skill_cache:
        path = os.path.join(_SKILLS_DIR, skill_dir, "SKILL.md")
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        _skill_cache[skill_dir] = re.sub(
            r"^---\n.*?\n---\n", "", raw, count=1, flags=re.DOTALL
        )
    return _skill_cache[skill_dir]


# ── Support-resources tool (Python FunctionTool — sync path) ──────────────
# ADK automatically wraps plain Python functions as FunctionTool objects.
# The docstring becomes the tool description visible to the model.

_resources_script = os.path.join(
    _SKILLS_DIR, "support_resources", "scripts", "get_support_resources.py"
)
_spec = importlib.util.spec_from_file_location("_bullystop_resources", _resources_script)
_resources_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_resources_mod)
_get_resources_impl = _resources_mod.get_support_resources


def get_support_resources(country: str) -> str:
    """
    Returns verified anti-bullying and mental health support resources for a country.
    Covers hotlines, government programs, and websites. Use 'default' if unknown.
    Always call this tool instead of inventing phone numbers or website URLs.
    """
    result = _get_resources_impl(country)
    return json.dumps(result, ensure_ascii=False)


# ── Specialized sub-agents ─────────────────────────────────────────────────

hearme_agent = Agent(
    name="hearme_agent",
    model=MODEL_NAME,
    description=(
        "Warm, empathetic support for students experiencing or witnessing bullying. "
        "Validates feelings, gives 3 actionable next steps, and surfaces verified "
        "crisis resources when severity is high or the student expresses distress."
    ),
    instruction=_load_skill_body("hearme_skill").format(
        severity="indicated in the [CONTEXT: ...] header at the top of the message"
    ),
    tools=[get_support_resources],
)

parentguide_agent = Agent(
    name="parentguide_agent",
    model=MODEL_NAME,
    description=(
        "Calm, practical guidance for parents or guardians whose child is being bullied: "
        "warning signs, how to open the conversation, a school action plan, and a "
        "ready-to-send email template."
    ),
    instruction=_load_skill_body("parentguide_skill"),
    tools=[get_support_resources],
)

protocol_agent = Agent(
    name="protocol_agent",
    model=MODEL_NAME,
    description=(
        "Structured, professional intervention protocols for teachers and school "
        "administrators: step-by-step timeline, incident documentation template, "
        "and draft family-communication emails."
    ),
    instruction=_load_skill_body("protocol_skill"),
    tools=[get_support_resources],
)

# ── Orchestrator ───────────────────────────────────────────────────────────

_ORCHESTRATOR_INSTRUCTION = """\
You are the BullyStop Orchestrator Agent. Every message you receive starts with a
system-injected header in this format:

  [CONTEXT: role=<student|parent|teacher>, severity=<low|medium|high>, country=<name|default>]

Your ONLY job is to read the role from that header and immediately transfer control to
the matching specialized agent — do NOT generate any response yourself.

Routing rules (apply exactly as written, no exceptions):
  role=student  → transfer_to_agent: hearme_agent
  role=parent   → transfer_to_agent: parentguide_agent
  role=teacher  → transfer_to_agent: protocol_agent

Transfer immediately upon reading the role. Never ask a question. Never reply directly.
"""

orchestrator_agent = Agent(
    name="orchestrator",
    model=MODEL_NAME,
    description=(
        "Routes each BullyStop request to the correct specialized support agent "
        "based on the user's role (student / parent / teacher)."
    ),
    instruction=_ORCHESTRATOR_INSTRUCTION,
    sub_agents=[hearme_agent, parentguide_agent, protocol_agent],
)

# ── Shared session service and root runner ─────────────────────────────────

session_service = InMemorySessionService()

orchestrator_runner = Runner(
    agent=orchestrator_agent,
    app_name="bullystop",
    session_service=session_service,
)

# ── Public API ─────────────────────────────────────────────────────────────


def run_adk(
    role: str,
    severity: str,
    country: str,
    user_message: str,
    session_id: str,
) -> tuple[str, bool]:
    """
    Runs one conversation turn through the ADK multi-agent pipeline.

    Injects a [CONTEXT] header so the orchestrator can route without a separate
    LLM classification call, then collects the final text reply from the
    specialized sub-agent.

    Returns
    -------
    (final_text, tool_was_called)
        tool_was_called is True if any sub-agent invoked get_support_resources
        during this turn — used by the caller to decide whether the deterministic
        safety backstop needs to force-show crisis resources.
    """
    from google.genai import types  # local import: keeps module importable without SDK

    context_header = (
        f"[CONTEXT: role={role}, severity={severity}, country={country}]\n"
    )
    content = types.Content(
        role="user",
        parts=[types.Part(text=context_header + user_message)],
    )

    final_text = ""
    tool_was_called = False

    try:
        for event in orchestrator_runner.run(
            user_id=session_id,
            session_id=session_id,
            new_message=content,
        ):
            # Surface API errors (quota, rate-limit, etc.) carried as event fields
            # so they propagate to the caller's exception handler instead of silently
            # returning an empty string that triggers the generic fallback message.
            if event.error_code or event.error_message:
                msg = event.error_message or event.error_code or "unknown error"
                if event.error_code:
                    msg = f"{event.error_code}: {msg}"
                raise RuntimeError(f"[ADK error event] {msg}")

            # Track any get_support_resources call anywhere in the event stream.
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if (
                        hasattr(part, "function_call")
                        and part.function_call
                        and part.function_call.name == "get_support_resources"
                    ):
                        tool_was_called = True

            if event.is_final_response() and event.content:
                candidate = "".join(
                    p.text
                    for p in (event.content.parts or [])
                    if hasattr(p, "text") and p.text
                ).strip()
                if candidate:
                    final_text = candidate
                    break

    except Exception:
        logging.exception("[ADK] orchestrator_runner.run() failed")
        raise

    return final_text, tool_was_called


# ── Async / MCP factory (production deployment pattern) ───────────────────


async def create_agents_with_mcp():
    """
    Rebuilds the same agent graph, but each sub-agent's get_support_resources
    tool is served by mcp_server.py over the MCP stdio protocol instead of the
    direct Python function call used by the Gradio demo.

    Use this in an async deployment (FastAPI + uvicorn, Kaggle notebook with
    asyncio) rather than the sync Gradio path.

    Returns (orchestrator_agent, exit_stack).
    Call ``await exit_stack.aclose()`` to stop the MCP subprocess when done.

    Example::

        orch, stack = await create_agents_with_mcp()
        runner = Runner(agent=orch, app_name="bullystop",
                        session_service=InMemorySessionService())
        # ... drive turns ...
        await stack.aclose()
    """
    from contextlib import AsyncExitStack

    from google.adk.tools.mcp_tool import MCPToolset, StdioServerParameters

    exit_stack = AsyncExitStack()
    mcp_tools, mcp_ctx = await MCPToolset.from_server(
        connection_params=StdioServerParameters(
            command=sys.executable,
            args=[_MCP_SERVER],
        )
    )
    await exit_stack.enter_async_context(mcp_ctx)
    mcp_tool_list = list(mcp_tools)

    h = Agent(
        name="hearme_mcp",
        model=MODEL_NAME,
        description=hearme_agent.description,
        instruction=hearme_agent.instruction,
        tools=mcp_tool_list,
    )
    p = Agent(
        name="parentguide_mcp",
        model=MODEL_NAME,
        description=parentguide_agent.description,
        instruction=parentguide_agent.instruction,
        tools=mcp_tool_list,
    )
    t = Agent(
        name="protocol_mcp",
        model=MODEL_NAME,
        description=protocol_agent.description,
        instruction=protocol_agent.instruction,
        tools=mcp_tool_list,
    )
    orch = Agent(
        name="orchestrator_mcp",
        model=MODEL_NAME,
        description=orchestrator_agent.description,
        instruction=_ORCHESTRATOR_INSTRUCTION,
        sub_agents=[h, p, t],
    )
    return orch, exit_stack
