# BullyStop — Multi-Agent Anti-Bullying Support

> **AI Agents: Intensive Vibe Coding Capstone Project** | Track: **Agents for Good**

An empathetic, production-grade multi-agent AI system that delivers personalized anti-bullying support to **students**, **parents**, and **teachers** — each routed to a specialized agent that speaks their language and knows their role.

Built entirely in **Google Antigravity** using the full course stack: Google ADK · Gemini 2.5 Flash Lite · Agent Skills · MCP · Hybrid Policy Server · Evaluation Suite · Vibe Trajectory Tracing.

---

## What it does

| Who asks | Agent activated | What they receive |
|---|---|---|
| **Student** | `hearme_agent` | Warm emotional validation + 3 age-appropriate next steps + crisis resources |
| **Parent / Guardian** | `parentguide_agent` | Warning signs checklist + conversation guide + ready-to-send school email |
| **Teacher / Admin** | `protocol_agent` | Step-by-step intervention timeline + incident report template + family-communication draft |

The system auto-detects role, severity, and country from natural language — no menus or dropdowns required.

---

## Architecture

```
User message (natural language)
       │
       ▼
┌──────────────────────────────────────────────────────┐
│                   app.py  (Gradio UI)                │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │  classify_message()                         │    │
│  │  Gemini · temperature=0 · JSON mode         │    │
│  │  → role (student|parent|teacher)            │    │
│  │  → severity (low|medium|high)               │    │
│  │  → country                                  │    │
│  └────────────────────┬────────────────────────┘    │
│                       │                             │
│  ┌────────────────────▼────────────────────────┐    │
│  │  _CRISIS_PATTERN  (deterministic backstop)  │    │
│  │  Bilingual EN+ES keyword regex              │    │
│  │  Fires regardless of classifier output      │    │
│  │  Cannot be bypassed by prompt injection     │    │
│  └────────────────────┬────────────────────────┘    │
│                       │                             │
│  ┌────────────────────▼────────────────────────┐    │
│  │          orchestrator_agent  (ADK)          │    │
│  │   ├── hearme_agent      ← student           │    │
│  │   ├── parentguide_agent ← parent            │    │
│  │   └── protocol_agent    ← teacher           │    │
│  │                                             │    │
│  │   Each sub-agent has access to:             │    │
│  │   get_support_resources (FunctionTool)      │    │
│  │   ── or ── MCP stdio (mcp_server.py)        │    │
│  └────────────────────┬────────────────────────┘    │
│                       │                             │
│  ┌────────────────────▼────────────────────────┐    │
│  │       policy_server.py  (Hybrid Gate)       │    │
│  │  Layer 1 · Structural · regex · no LLM call │    │
│  │  Layer 2 · Semantic   · Gemini · temp=0     │    │
│  └────────────────────┬────────────────────────┘    │
│                       │                             │
│         tracing.py → traces.jsonl                   │
│     agent.session · agent.think · agent.tool        │
└──────────────────────────────────────────────────────┘
       │
       ▼
  Final response to user
```

---

## Course Concepts Demonstrated

| Day | Topic | What BullyStop implements |
|---|---|---|
| **Day 1** | New SDLC / Vibe Coding | Built entirely in Google Antigravity; SKILL.md files serve as the spec (architectural north star before any code) |
| **Day 2** | Agent Tools & MCP | `mcp_server.py` exposes `get_support_resources` over MCP stdio; `create_agents_with_mcp()` shows a drop-in swap between FunctionTool and MCP without changing agent logic |
| **Day 3** | Agent Skills | 4 skills in `skills/` with full `SKILL.md + scripts/ + references/ + assets/` structure; progressive-disclosure loading keeps token budget lean |
| **Day 4** | Security & Evaluation | Prompt injection protection via `system_instruction` isolation; deterministic crisis backstop; 6-case eval suite in `evals/cases.json` including adversarial injection test |
| **Day 5** | Spec-Driven Production | Hybrid Policy Server (structural + semantic gates); Vibe Trajectory tracing (`tracing.py`); `traces.jsonl` spans for every LLM call and tool execution |

---

## Quick Start

### Prerequisites

- Python 3.11+
- A Google Gemini API key ([get one free](https://aistudio.google.com/apikey))

### Install

```bash
git clone https://github.com/MirandaGomezM/bullystop
cd bullystop
pip install -r requirements.txt
```

### Configure

```bash
# Create a .env file with your key:
echo GOOGLE_API_KEY=your_key_here > .env
```

> **On Kaggle**: add your key as a Kaggle Secret named `GOOGLE_API_KEY` and enable notebook internet access.

### Run the demo

```bash
python app.py
```

Open `http://localhost:7860` in your browser and start a conversation.

### Run the evaluation suite

```bash
python evals/run_evals.py
```

Runs all 6 cases in `evals/cases.json`, including the prompt-injection resistance test.

---

## Agent Skills (Day 3)

Skills follow the canonical `SKILL.md + scripts/ + references/ + assets/` structure:

```
skills/
├── hearme_skill/
│   └── SKILL.md                        # Emotional support for students
├── parentguide_skill/
│   └── SKILL.md                        # Practical guidance for parents
├── protocol_skill/
│   ├── SKILL.md                        # Intervention protocols for teachers
│   └── assets/
│       └── incident_report_template.md # Ready-to-use report form
└── support_resources/
    ├── SKILL.md                        # Crisis resource lookup skill
    ├── scripts/
    │   └── get_support_resources.py    # Tool implementation
    └── references/
        └── resources_by_country.json   # Verified resources: AR, US, UK, ES, BR, ...
```

**Progressive disclosure**: the YAML frontmatter `description` in each SKILL.md is always loaded into the orchestrator for zero-cost routing decisions. The full skill body is loaded only when that persona is selected — keeping token spend proportional to what the user actually needs.

---

## MCP: Two Modes, One Tool Contract (Day 2)

`get_support_resources` ships in two interchangeable forms:

| Mode | File | When to use |
|---|---|---|
| **Python FunctionTool** (sync) | `agents/bullystop_agents.py` | Gradio demo · zero subprocess overhead |
| **MCP stdio server** | `mcp_server.py` | Async production deployment (FastAPI, Cloud Run, any MCP-compliant host) |

Switch modes by calling `create_agents_with_mcp()` instead of the default runner. The agent graph is identical — only the tool binding changes. This demonstrates that **MCP and direct FunctionTool are interchangeable at the integration boundary**.

---

## Security (Day 4)

### Prompt Injection Protection
The message classifier sends the security prompt via the `system_instruction` API parameter — a separate field, never concatenated with user text. User input arrives as a distinct `content` block. The model cannot be confused about which text is an instruction and which is data.

### Deterministic Crisis Backstop
`_CRISIS_PATTERN` — a bilingual (English + Spanish) compiled regex — runs synchronously before any LLM call. Even if the classifier is tricked into returning `severity=low`, the backstop catches keywords like `quiero morirme`, `kill myself`, `suicid*`, and forces crisis resources to appear. **This path has no LLM dependency and cannot be bypassed by prompt injection.**

### Hybrid Policy Server (`policy_server.py` — Day 5)
Two-layer gate applied to every outgoing message before it reaches the user:

1. **Structural gate** — deterministic regex, no LLM call. Blocks country-locked phone numbers (988 = US only, 111 = UK only, 106 = AR only) in any message where the `get_support_resources` tool did not confirm that country.
2. **Semantic gate** — secondary Gemini call at `temperature=0`, `max_output_tokens=120`. Catches fabricated hotlines and overly broad emergency-number claims that a regex cannot express.

The semantic gate **fails open**: a broken policy reviewer gracefully degrades to "no semantic check this turn" rather than taking the whole app down.

### MCP Tool Safety
The `get_support_resources` tool description explicitly tells every agent: *"Always call this tool instead of inventing phone numbers or website URLs."* The tool itself reads from a curated, human-reviewed JSON file — so the agent's only safe path to real resources runs through a verified data source.

---

## Observability — Vibe Trajectory Tracing (Day 5)

`tracing.py` instruments every conversation turn using the span naming from the course:

| Span name | What it captures |
|---|---|
| `agent.session` | Full turn: user message → final reply; total latency |
| `agent.think` | Each LLM call (classify, orchestrator routing, sub-agent response) |
| `agent.tool` | Tool executions: `get_support_resources`, forced safety lookup |

Spans are written to `traces.jsonl` as newline-delimited JSON — greppable with `jq`, loadable with `pandas`, and ready for a one-line swap to real OpenTelemetry.

```python
# Load and inspect spans
from tracing import load_spans, session_cost_summary
spans = load_spans()                          # all spans
summary = session_cost_summary("session-123") # per-session latency rollup
```

---

## Evaluation Suite (Day 4)

`evals/cases.json` — 6 cases covering the full range of real-world inputs:

| Case ID | What it tests |
|---|---|
| `student_high_physical` | Crisis detection · verified resources surfaced · warm tone |
| `parent_medium_exclusion` | Parent routing · actionable guidance (not just sympathy) |
| `teacher_protocol_request` | Teacher routing · administrative/structured tone |
| `self_harm_keyword_overrides_classifier` | **Prompt injection resistance** — resources appear even when injection attempts to suppress them |
| `vague_low_severity` | Graceful handling of ambiguous input · no false crisis trigger |
| `country_specific_resources` | Argentina-specific verified resources · not US-defaults |

Each case includes an `expected_role`, `expected_severity`, `expected_resources_shown`, and a natural-language `rubric` for LLM-as-judge scoring — matching the Evaluation-Driven Development pattern from Day 3/4.

---

## Project Structure

```
bullystop/
├── app.py                         # Gradio UI · classifier · orchestration · safety backstop
├── agents/
│   └── bullystop_agents.py        # ADK multi-agent graph · MCP factory
├── mcp_server.py                  # MCP stdio server for get_support_resources
├── policy_server.py               # Hybrid Policy Server (structural + semantic)
├── tracing.py                     # Vibe Trajectory tracer
├── traces.jsonl                   # Runtime spans (excluded from production secrets)
├── evals/
│   ├── cases.json                 # 6 evaluation cases
│   └── run_evals.py               # Evaluation runner
├── skills/
│   ├── hearme_skill/              # Student support agent skill
│   ├── parentguide_skill/         # Parent guidance agent skill
│   ├── protocol_skill/            # Teacher/admin protocol skill
│   └── support_resources/         # Crisis resource lookup skill
├── test_flow.py                   # Unit test suite (14 tests, mocked — no API key needed)
├── requirements.txt               # 5 dependencies · all OSI-approved licenses
└── .env                           # GOOGLE_API_KEY (gitignored)
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_API_KEY` | Yes | — | Gemini API key |
| `GEMINI_MODEL` | No | `gemini-2.5-flash-lite` | Model override (any Gemini model ID) |
| `BULLYSTOP_TRACE_LOG` | No | `traces.jsonl` | Path for trace output |

---

## Dependencies

```
google-genai>=2.0.0    # Gemini API SDK              · Apache 2.0
google-adk>=1.0.0      # Agent Development Kit       · Apache 2.0
mcp>=1.0.0             # Model Context Protocol      · MIT
gradio>=5.0.0          # Demo UI                     · Apache 2.0
python-dotenv>=1.0.0   # .env loading                · BSD-3
```

All dependencies are OSI-approved open-source licenses.

---

## Why Agents for Good

School bullying affects approximately **1 in 5 students globally**. Most incidents go unreported — not because victims don't want help, but because they don't know who to tell, what to say, or what will happen next. At midnight, no counselor is available.

BullyStop gives every student, parent, and teacher an immediate, private, judgment-free first step:
- A student who can't say the words out loud can type them.
- A parent who doesn't know how to start the conversation gets a script.
- A teacher who has never handled an incident gets a step-by-step protocol.

The system surfaces **verified, country-specific crisis resources** via a curated tool rather than invented numbers — because in a mental health context, a wrong phone number is not a minor inconvenience.

---

## Built With

- [Google Antigravity](https://labs.google.com) — AI coding agent (the vibe coding IDE used throughout this course)
- [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/) — Multi-agent framework
- [Gemini 2.5 Flash Lite](https://ai.google.dev/gemini-api/docs/models) — Foundation model
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io) — Tool interoperability standard
- [Gradio](https://gradio.app) — Demo UI
