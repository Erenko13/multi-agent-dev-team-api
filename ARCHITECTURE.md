# Multi-Agent Development Team — Implementation Plan

## Context

Build a multi-agent software development team using **Python + LangGraph** that collaborates to generate full-stack web applications. Agents are distributed across **multiple free-tier LLM providers** — Groq (primary for code generation), Gemini (for review/testing), and optionally Ollama (for local GPU users). Five specialized agents (PM, Architect, Developer, Reviewer, Tester) work in a coordinated pipeline with human-in-the-loop checkpoints.

---

## Architecture Overview

```
User Input → [PM Agent] → [Architect Agent] → ★ HUMAN APPROVAL ★
                                                      |
                                               [Developer Agent]
                                                      |
                                               [Reviewer Agent]
                                                      |
                                          (approved?) ─┬─ No → back to Developer (max 3x)
                                                       └─ Yes ↓
                                                [Tester Agent]
                                                      |
                                              ★ HUMAN APPROVAL ★ → Done
```

---

## Project Structure

```
multi-agent-dev-team-api/
├── pyproject.toml
├── .env.example
├── config.yaml
├── sandbox/
│   └── Dockerfile               # Docker image for sandboxed shell execution
├── src/
│   ├── __init__.py
│   ├── main.py                  # CLI entry point (Rich-based interactive)
│   ├── config.py                # YAML config loader
│   ├── llm.py                   # LLM factory (Groq/Gemini/Ollama/OpenAI-compat)
│   ├── state.py                 # AgentState TypedDict (shared graph state)
│   ├── graph.py                 # LangGraph StateGraph definition
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py               # FastAPI application, lifespan, CORS
│   │   ├── routes.py            # API endpoint definitions
│   │   ├── schemas.py           # Pydantic request/response models
│   │   ├── sessions.py          # SessionManager: pipeline lifecycle + approval bridge
│   │   └── dependencies.py      # FastAPI dependency injection
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── pm.py                # PM: requirements → user stories + task plan
│   │   ├── architect.py         # Architect: stories → architecture doc + tech stack
│   │   ├── developer.py         # Developer: architecture → code files (tool-calling loop)
│   │   ├── reviewer.py          # Reviewer: code → review comments + approve/reject
│   │   └── tester.py            # Tester: code → test files + run tests
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── file_io.py           # write_file, read_file, list_directory
│   │   ├── shell.py             # run_shell_command (host or Docker sandbox)
│   │   ├── search.py            # search_codebase (regex across files)
│   │   └── project.py           # create_project_structure
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── pm.py
│   │   ├── architect.py
│   │   ├── developer.py
│   │   ├── reviewer.py
│   │   └── tester.py
│   └── utils/
│       ├── __init__.py
│       ├── container.py         # DockerSandbox lifecycle manager
│       ├── output.py            # Rich console formatting
│       └── workspace.py         # Workspace directory management
└── tests/
    ├── __init__.py
    ├── test_state.py
    ├── test_graph.py
    └── test_tools.py
```

---

## Agentic Architecture

### Pattern: Supervisor Graph with Sequential Pipeline + Review Loop

This is a **LangGraph StateGraph** where each agent is a **node** and the graph itself acts as the supervisor/orchestrator. There is no separate "supervisor agent" LLM making routing decisions — the routing logic is encoded as **conditional edges** in the graph definition. This avoids wasting tokens on routing decisions that are deterministic.

```
                    ┌─────────────────────────────────────────────────┐
                    │              LangGraph StateGraph               │
                    │                                                 │
 User Input ──►     │  ┌────┐    ┌───────────┐    ┌──────────────┐    │
                    │  │ PM │───►│ Architect │───►│ HUMAN REVIEW │    │
                    │  └────┘    └───────────┘    └──────┬───────┘    │
                    │                                    │            │
                    │                          ┌──── approve? ────┐   │
                    │                          │ NO               │YES│
                    │                          ▼                  ▼   │
                    │                    ┌───────────┐    ┌─────────┐ │
                    │                    │ Architect │    │Developer│ │
                    │                    │ (re-draft)│    └────┬────┘ │
                    │                    └───────────┘         │      │
                    │                                          ▼      │
                    │                         ┌──────────────────┐    │
                    │                         │     Reviewer     │    │
                    │                         └────────┬─────────┘    │
                    │                                  │              │
                    │                     ┌──── approved? ────┐       │
                    │                     │ NO (& iter < 3)   │YES    │
                    │                     ▼                    ▼      │
                    │               ┌───────────┐      ┌────────┐     │
                    │               │ Developer │      │ Tester │     │
                    │               │ (revision)│      └───┬────┘     │
                    │               └───────────┘          │          │
                    │                                       ▼         │
                    │                              ┌──────────────┐   │
                    │                              │ HUMAN REVIEW │   │
                    │                              └──────┬───────┘   │
                    │                                     │           │
                    │                                  approve?       │
                    │                                YES │            │
                    │                                    ▼            │
                    │                                  [END]          │
                    └─────────────────────────────────────────────────┘
```

### Three Core Architecture Principles

**1. Shared state, not message passing** — Agents do NOT talk to each other directly. They all read from and write to a single `AgentState` dictionary that flows through the graph. Each agent only touches its own section of the state. The `messages` field is the only append-only field (used for logging).

```
PM writes:        user_stories, task_plan
Architect reads:  user_stories, task_plan
Architect writes: architecture_doc, tech_stack, folder_structure
Developer reads:  architecture_doc, folder_structure, review_comments
Developer writes: generated_files
Reviewer reads:   generated_files, architecture_doc
Reviewer writes:  review_comments, review_approved
Tester reads:     generated_files
Tester writes:    test_files, test_results
```

**2. Two agent patterns** — Pure reasoning agents (PM, Architect) make a single LLM call and return structured output. Tool-calling agents (Developer, Reviewer, Tester) run in a ReAct loop where the LLM calls tools iteratively until done.

**3. Graph-level routing** — Agents don't decide "who goes next." The graph's conditional edges handle all routing based on state fields (`review_approved`, `review_iteration`, `architecture_approved`).

### Why This Pattern (vs Alternatives)

| Alternative | Why Not |
|---|---|
| **Supervisor agent** (LLM decides routing) | Wastes tokens on routing decisions that are deterministic for our workflow |
| **Hierarchical multi-agent** (sub-teams) | Over-engineered for 5 agents — useful at 15+ agents |
| **Swarm / peer-to-peer** | No clear workflow — agents would duplicate work or deadlock |
| **CrewAI / AutoGen** | LangGraph gives more control over state, routing, and human-in-the-loop |

### LLM Instance Model

Each agent gets its **own LLM instance** (separate Python object), but they can share the same underlying model/provider. "Separate instance" means separate `ChatGroq(...)` or `ChatGoogleGenerativeAI(...)` object — NOT a separate server or API key.

```python
# What happens at runtime — each agent gets its own LLM object:
pm_llm       = ChatGroq(model="llama-3.1-8b-instant", ...)      # own instance
architect_llm = ChatGroq(model="llama-3.3-70b-versatile", ...)   # own instance, different model
developer_llm = ChatGroq(model="llama-3.3-70b-versatile", ...)   # own instance + .bind_tools()
reviewer_llm  = ChatGoogleGenerativeAI(model="gemini-2.5-flash") # different PROVIDER entirely
tester_llm    = ChatGoogleGenerativeAI(model="gemini-2.5-flash") # same provider as reviewer
```

What differs per agent:

| Aspect | Varies? | Example |
|---|---|---|
| System prompt | Yes | "You are a PM..." vs "You are a developer..." |
| Bound tools | Yes | Developer gets `write_file`, PM gets none |
| Input context | Yes | Each agent reads different AgentState fields |
| Model / provider | Optionally | PM on Groq 8B, Reviewer on Gemini Flash |

**No shared conversation history** — each agent starts fresh with only its system prompt + relevant state fields injected as a HumanMessage. The graph state is the shared memory, not the LLM context. This keeps token usage low and prevents prompt pollution.

### Checkpointing

A checkpoint is a **serialized snapshot of the entire AgentState** saved automatically after every node executes.

```
Checkpoint 0  [START]           → empty state + user_requirements
Checkpoint 1  [after PM]        → + user_stories, task_plan
Checkpoint 2  [after Architect] → + architecture_doc, tech_stack, folder_structure
Checkpoint 3  [after Human #1]  → + architecture_approved = True
Checkpoint 4  [after Developer] → + generated_files
Checkpoint 5  [after Reviewer]  → + review_comments, review_approved=False, iteration=1
Checkpoint 6  [after Developer] → + updated generated_files (revision)
Checkpoint 7  [after Reviewer]  → + review_approved=True, iteration=2
Checkpoint 8  [after Tester]    → + test_files, test_results
Checkpoint 9  [after Human #2]  → + final_approved = True → END
```

Checkpoints serve three purposes:

| Purpose | How It Works |
|---|---|
| **Human-in-the-loop** | `interrupt()` pauses execution, saves state. CLI resumes with `Command(resume=...)`. Without checkpoints, interrupt can't work. |
| **Loop state preservation** | Developer-Reviewer loop: each iteration reads `review_comments` from the previous checkpoint. `review_iteration` counter persists correctly. |
| **Fault recovery** | If an agent crashes (API timeout, rate limit), re-invoking the graph resumes from the last checkpoint — earlier agents don't re-run. Critical for free-tier APIs. |

Uses `MemorySaver` (in-memory) for CLI. Can upgrade to `SqliteSaver` for persistence across process restarts.

---

## Key Design Decisions

### 1. State Schema (`src/state.py`)

Single `AgentState(TypedDict)` shared across all nodes:

| Field | Type | Set By |
|---|---|---|
| `messages` | `Annotated[list[BaseMessage], operator.add]` | All (append-only) |
| `user_requirements` | `str` | User input |
| `user_stories` | `list[str]` | PM |
| `task_plan` | `list[TaskItem]` | PM |
| `architecture_doc` | `str` (markdown) | Architect |
| `folder_structure` | `list[str]` | Architect |
| `tech_stack` | `dict[str, str]` | Architect |
| `architecture_approved` | `bool` | Human checkpoint |
| `generated_files` | `list[FileOutput]` | Developer |
| `review_comments` | `list[ReviewComment]` | Reviewer |
| `review_approved` | `bool` | Reviewer |
| `review_iteration` | `int` | Reviewer (incremented each pass) |
| `test_files` | `list[FileOutput]` | Tester |
| `test_results` | `list[TestResult]` | Tester |
| `tests_passing` | `bool` | Tester |
| `workspace_path` | `str` | Init |

### 2. LangGraph Workflow (`src/graph.py`)

- **Nodes**: `pm_agent`, `architect_agent`, `human_approve_architecture`, `developer_agent`, `reviewer_agent`, `tester_agent`, `human_approve_final`
- **Human checkpoints** use `interrupt()` inside dedicated nodes — the modern LangGraph pattern. The CLI resumes with `Command(resume=...)`.
- **Conditional edge** after Reviewer: routes back to Developer if `review_approved=False AND review_iteration < 3`, otherwise proceeds to Tester.
- **Conditional edge** after final approval: routes to END if approved, back to Developer if rejected.
- **Checkpointer**: `MemorySaver` (in-memory, suitable for CLI).

### 3. LLM Configuration (`config.yaml` + `src/llm.py`)

Agents are **distributed across multiple free-tier providers** to maximize daily throughput.

Supports 4 providers via a factory function (`create_llm()` in `src/llm.py`):

| Provider | Package | Free Tier Limits | Role |
|---|---|---|---|
| `groq` | `langchain-groq` | 30 RPM, 1K req/day, 100K tok/day (70B) / 14.4K req/day, 500K tok/day (8B) | **PM, Architect, Developer** |
| `gemini` | `langchain-google-genai` | 10 RPM, 250 req/day, 250K TPM | **Reviewer, Tester** |
| `ollama` | `langchain-ollama` | Unlimited (local) | **Optional** (needs GPU) |
| `openai_compatible` | `langchain-openai` | Varies | **Optional** (any endpoint) |

**Optimized multi-provider agent assignment:**

| Agent | Provider | Model | Why This Assignment |
|---|---|---|---|
| **PM** | Groq | Llama 3.1 8B Instant | Simple task breakdown — uses 8B's generous 500K tok/day pool |
| **Architect** | Groq | Llama 3.3 70B | Needs strong reasoning for design decisions |
| **Developer** | Groq | Llama 3.3 70B | Needs best code gen + fast tool-calling (30 RPM) |
| **Reviewer** | **Gemini** | **2.5 Flash** | Separate token pool from Groq; 10 RPM is enough for review loops |
| **Tester** | **Gemini** | **2.5 Flash** | Separate token pool from Groq; 10 RPM is enough for test loops |

**Token budget per run (estimated):**

| Agent | Provider | ~Tokens | ~Requests |
|---|---|---|---|
| PM | Groq 8B | ~5K | 1-2 |
| Architect | Groq 70B | ~10K | 1-2 |
| Developer | Groq 70B | ~40K | 10-20 (tool loop) |
| Reviewer | Gemini Flash | ~20K | 5-10 (tool loop) |
| Tester | Gemini Flash | ~20K | 5-10 (tool loop) |

**Daily capacity:** ~3-4 full project runs/day
- Groq 70B budget (~50K/run): supports ~2 runs from 100K/day, plus retries
- Groq 8B budget (~5K/run): essentially unlimited from 500K/day
- Gemini budget (~40K/run, ~15-20 req/run): supports ~6+ runs from 250 req/day

**Why not Mistral?** Mistral has incredible free limits (1B tokens/month) but only **2 RPM**. Tool-calling agents (Reviewer, Tester) make 5-15 LLM calls per run — at 2 RPM, a single review pass takes ~2.5-8 minutes of rate-limit waiting. Mistral could work for PM or Architect (single-call agents) in the future.

### 4. Agent Details

| Agent | Tools | Output Strategy |
|---|---|---|
| **PM** | None (pure reasoning) | `with_structured_output()` → `PMOutput` Pydantic model |
| **Architect** | None (pure reasoning) | `with_structured_output()` → `ArchitectOutput` |
| **Developer** | `write_file`, `read_file`, `list_directory`, `create_project_structure`, `run_shell_command` | Tool-calling loop (max 30 iterations) |
| **Reviewer** | `read_file`, `search_codebase`, `list_directory` | Tool-calling + structured output for comments |
| **Tester** | `write_file`, `read_file`, `run_shell_command`, `list_directory` | Tool-calling + test execution |

- Developer/Reviewer/Tester use `llm.bind_tools()` with a manual invoke loop inside the node function.
- All structured output has a fallback: if `with_structured_output()` fails, parse JSON from freeform text.
- Tools are scoped to workspace via factory functions that capture `workspace_path`.

### 5. Safety

- `run_shell_command` uses an allowlist of safe command prefixes (`pip`, `npm`, `pytest`, `node`, etc.)
- Dangerous patterns (`rm -rf`, `sudo`, `curl`, `eval`) are blocked outright
- All file tools validate paths stay within workspace (prevent path traversal)
- Developer-Reviewer loop hard-capped at 3 iterations
- Shell commands execute inside a **Docker sandbox** by default — see section below

### 6. Docker Sandbox (`src/utils/container.py` + `sandbox/Dockerfile`)

By default, shell commands (`pip install`, `npm install`, `pytest`, etc.) execute inside a **throwaway Docker container** rather than directly on the host. This isolates dependency installation and test execution from the user's machine.

```
┌─────────────────────────────────────────────────┐
│  Host Machine                                    │
│                                                  │
│  multi-agent-dev-team/                           │
│  ├── src/ (agent code runs here)                 │
│  └── output/ ◄──── bind mount ────┐             │
│                                     │             │
│  ┌──────────────────────────────────┼──────────┐ │
│  │  Docker Container (devteam-xxx)  │          │ │
│  │                                  │          │ │
│  │  /workspace/ ◄───────────────────┘          │ │
│  │  ├── backend/app.py                          │ │
│  │  ├── frontend/src/App.jsx                    │ │
│  │  └── package.json                            │ │
│  │                                              │ │
│  │  pip install ──► installs HERE, not on host  │ │
│  │  npm install ──► installs HERE, not on host  │ │
│  │  pytest      ──► runs HERE, not on host      │ │
│  └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

**Where each piece runs:**

```
┌─────────────────────────────────────────────────────┐
│  YOUR HOST MACHINE                                   │
│                                                      │
│  .venv/                                              │
│  └── python -m src.main  ◄── agent pipeline runs HERE│
│      │                                               │
│      │ (calls Groq + Gemini APIs)                   │
│      │                                               │
│      └── run_shell_command("pip install flask")     │
│                    │                                 │
│                    ▼                                 │
│      ┌────────────────────────────────┐             │
│      │  Docker Container               │             │
│      │  (devteam-sandbox)              │             │
│      │                                 │             │
│      │  /workspace/  ◄── the generated │             │
│      │    ├── app.py    project lives  │             │
│      │    ├── package.json  here       │             │
│      │                                 │             │
│      │  pip install runs HERE          │             │
│      └────────────────────────────────┘             │
└─────────────────────────────────────────────────────┘
```

The agent pipeline itself (Python process, LangGraph, LLM API calls) stays on the host — only shell commands emitted by the Developer and Tester agents get dispatched into the container.

**Architecture:**

- **File tools** (`write_file`, `read_file`) operate on `./output/` on the host directly.
- That directory is **bind-mounted** into the container at `/workspace/`, so the container sees the same files the agents wrote.
- **Shell tool** (`run_shell_command`) dispatches into the container via `docker exec` when a `DockerSandbox` instance is present; otherwise it falls back to `subprocess.run()` on the host.
- The container runs `python:3.12-slim` with **Python 3.12 + Node.js 20** pre-installed (see `sandbox/Dockerfile`).
- Resource limits: **2 CPU cores, 2GB RAM**.

**Lifecycle:** `src/main.py` creates a `DockerSandbox` at startup, calls `start()` (which builds the image on first run, then launches the container detached), and passes it to the graph via `partial()` binding on the developer and tester nodes. A `try/finally` in `main()` ensures `sandbox.stop()` removes the container when the pipeline exits, crashes, or is interrupted.

**Fallback:** If `sandbox.enabled: true` is set but Docker isn't available (no daemon, missing binary, permission error), `DockerSandbox.is_docker_available()` returns `False` and the CLI prints a warning and runs shell commands directly on the host. Setting `sandbox.enabled: false` disables the sandbox unconditionally.

**Why not Docker-in-Docker?** The agent process doesn't run inside a container managing nested containers. It's a single host process that drives one sibling container via the host's Docker daemon. This is simpler, safer, and avoids the privileged-mode requirements of true DinD.

---

## API Layer (`src/api/`)

The project exposes a **FastAPI REST API** on top of the existing LangGraph pipeline. The API allows clients (future chat UI, external tools) to start pipelines, stream progress, and submit human approvals — all without touching the core agent/graph code.

### Architecture

```
Client (chat UI, curl, etc.)
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  FastAPI  (src/api/app.py)                              │
│                                                         │
│  POST /api/projects ──────┐                             │
│  GET  /api/projects/{id} ─┤                             │
│  GET  /api/projects/{id}/events (SSE) ─┤                │
│  POST /api/projects/{id}/approvals ────┤                │
│  DELETE /api/projects/{id} ────────────┤                │
│  GET  /api/health ─────────────────────┤                │
│                                        ▼                │
│                              ┌──────────────────┐       │
│                              │  SessionManager  │       │
│                              │  (sessions.py)   │       │
│                              └────────┬─────────┘       │
│                                       │                 │
│              ┌────────────────────────┼──────────┐      │
│              │ PipelineSession        │          │      │
│              │                        │          │      │
│              │  graph ────────────────┘          │      │
│              │  sandbox (DockerSandbox)          │      │
│              │  event_queues[] (SSE fan-out)     │      │
│              │  approval_event (asyncio.Event)   │      │
│              └──────────────────────────────────┘      │
└─────────────────────────────────────────────────────────┘
    │
    ▼
Existing code (UNCHANGED):
    src/graph.py, src/agents/*, src/tools/*, src/prompts/*
```

### Session Lifecycle

Each `POST /api/projects` creates an isolated **PipelineSession** with:

| Component | Per-Session? | Why |
|-----------|-------------|-----|
| `CompiledStateGraph` | Yes | Each session gets its own graph + `MemorySaver` checkpointer for state isolation |
| Workspace slot | Yes | One of 5 fixed directories (`output/project_1/` … `output/project_5/`) |
| `asyncio.Task` | Yes | Background pipeline execution |
| `DockerSandbox` | **Shared** | One container for the server lifetime; mounts all 5 slots at once |

**5 fixed workspace slots** (`project_1` … `project_5`) are created inside `output/` at server startup. A project is assigned to a free slot when it starts and releases it when it finishes. If all 5 are busy, `POST /api/projects` returns **503**. Project files persist in the slot after completion and are only cleared when the slot is reused for a new project.

**Slot ↔ container path mapping:**

```
Host filesystem              Docker container (/workspace bind-mount)
──────────────────           ────────────────────────────────────────
output/project_1/  ────────► /workspace/project_1/
output/project_2/  ────────► /workspace/project_2/
output/project_3/  ────────► /workspace/project_3/
output/project_4/  ────────► /workspace/project_4/
output/project_5/  ────────► /workspace/project_5/
```

`container_workspace_path` (e.g. `/workspace/project_2`) is stored in `AgentState` so the Developer and Tester agents pass it as the working directory to every `docker exec` call via `make_shell_tool(..., container_workdir=container_workspace_path)`.

### Async Execution Model

LangGraph's `graph.stream()` is synchronous (blocks on LLM API calls). The API wraps it with `asyncio.to_thread()` so the FastAPI event loop stays free for other requests.

```
FastAPI event loop                     Thread pool
      │                                     │
      │── asyncio.create_task() ──────────►  │
      │   (_run_pipeline)                    │
      │                                     │
      │   await to_thread(graph.stream) ──► │── graph.stream() ──► LLM API calls
      │   ◄── returns node events ──────────│
      │                                     │
      │   (interrupt detected)              │
      │   set status = awaiting_approval    │
      │   publish SSE event                 │
      │   await approval_event.wait() ─┐    │
      │                                │    │
      │── POST /approvals ────────────►│    │
      │   approval_event.set() ────────┘    │
      │                                     │
      │   await to_thread(graph.stream) ──► │── Command(resume=...) ──► LLM APIs
      │   ◄── returns node events ──────────│
      │                                     │
      │   (graph completed)                 │
      │   set status = completed            │
      │   publish SSE event                 │
```

### Human-in-the-Loop via API

The existing `interrupt()` mechanism in `graph.py` is unchanged. When the graph pauses:

1. `_run_pipeline()` detects the interrupt by inspecting `snapshot.tasks[*].interrupts`
2. Sets `session.status = awaiting_approval` and publishes an `approval_required` SSE event
3. Blocks on `session.approval_event.wait()` (an `asyncio.Event`)
4. Client sees the pending approval via `GET /projects/{id}` or the SSE stream
5. Client submits `POST /projects/{id}/approvals` with `{"approved": true/false, "feedback": "..."}`
6. The route handler stores the resume value and calls `approval_event.set()`
7. `_run_pipeline()` wakes up, resumes the graph with `Command(resume=resume_value)`

The interrupt data format from `graph.py` is passed through to the client verbatim:

**Architecture review** (`human_approve_architecture`):
```json
{
  "type": "architecture_review",
  "architecture_doc": "...",
  "tech_stack": {"backend": "FastAPI", ...},
  "folder_structure": ["src/app.py", ...]
}
```

**Final review** (`human_approve_final`):
```json
{
  "type": "final_review",
  "generated_files": ["src/app.py", ...],
  "test_results": [...],
  "tests_passing": true
}
```

### SSE Event Streaming

`GET /api/projects/{id}/events` returns a `text/event-stream` response. Events are published from the background pipeline task to per-subscriber `asyncio.Queue` instances (fan-out pattern).

**Event types:**

| Event | When | Data |
|-------|------|------|
| `pipeline_started` | Pipeline begins | `{project_id}` |
| `agent_completed` | An agent node finishes | `{agent, output_keys}` |
| `approval_required` | Graph hits `interrupt()` | Interrupt value (architecture/final review data) |
| `approval_submitted` | Client submits approval | `{approved, feedback}` |
| `pipeline_completed` | Pipeline finishes successfully | `{project_id}` |
| `pipeline_failed` | Pipeline errors out | `{error}` |
| `pipeline_cancelled` | Client cancels via DELETE | — |

A keepalive comment (`: keepalive`) is sent every 30 seconds to prevent proxy/client timeouts.

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| API layer is additive only — no changes to existing code | Agents, tools, graph, and CLI continue to work independently |
| One graph per session (not shared) | Each session needs its own `MemorySaver` checkpointer for state isolation |
| One shared `DockerSandbox` for the server lifetime | Mounting the entire `output/` once is simpler and cheaper than one container per session; all 5 slots are visible at `/workspace/project_1` … `/workspace/project_5` |
| 5 fixed workspace slots instead of unlimited UUID dirs | Caps concurrent resource usage (Docker memory/CPU limits apply once); projects persist in named, predictable directories |
| `container_workspace_path` in `AgentState` | Agents need the container-side path (e.g. `/workspace/project_2`) to set the correct `docker exec -w` working directory — separate from the host-side `workspace_path` used by file tools |
| Project files persist after pipeline completes | Slot is cleared only when reused, so generated code remains accessible until the next project starts in that slot |
| `asyncio.to_thread()` for graph execution | LangGraph is synchronous; wrapping in a thread prevents blocking the event loop |
| SSE over WebSocket | Simpler for unidirectional server-to-client streaming; sufficient for status updates |
| Module-level singleton for `SessionManager` DI | Avoids `app.state` coupling; easy to mock in tests |

---

## Dependencies

```toml
dependencies = [
    "langgraph>=1.1.6",
    "langchain-core>=0.3",
    "langchain-groq>=1.1.2",
    "langchain-google-genai>=2.1.0",
    "langchain-ollama>=1.1.0",
    "langchain-openai>=0.3",
    "pyyaml>=6.0",
    "rich>=13.0",
    "pydantic>=2.0",
    "python-dotenv>=1.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
]
```

---

## Implementation Order

**Phase 1 — Foundation**: `pyproject.toml`, `.env.example`, `config.yaml`, `state.py`, `config.py`, `llm.py`
**Phase 2 — Tools**: `file_io.py`, `shell.py`, `search.py`, `project.py`, `workspace.py`, `output.py`
**Phase 3 — Agents**: All 5 prompt files, then agents: PM → Architect → Developer → Reviewer → Tester
**Phase 4 — Orchestration**: `graph.py`, `main.py`
**Phase 5 — Testing**: Unit tests for tools, state, and graph routing

---

## Verification

1. `pip install -e .` — installs cleanly
2. Set `GROQ_API_KEY` in `.env` (free key from console.groq.com) and `GOOGLE_API_KEY` (free key from aistudio.google.com)
3. Run `python -m src.main` — enter a simple requirement like "Build a todo list app with FastAPI and React"
4. Verify: PM produces user stories → Architect produces architecture doc → human checkpoint pauses for approval → Developer writes files to `./output/` → Reviewer provides feedback → Tester writes and runs tests → final human approval
5. Check `./output/` contains a valid project structure with runnable code

## Config Defaults (`config.yaml`)

```yaml
default_provider: groq

providers:
  groq:
    model: "llama-3.3-70b-versatile"      # Strong reasoning + tool calling
    temperature: 0.2
    max_tokens: 8192

  groq_small:
    model: "llama-3.1-8b-instant"          # Lightweight tasks, 500K tok/day free
    temperature: 0.2
    max_tokens: 8192

  gemini:
    model: "gemini-2.5-flash"              # Good reasoning, separate free quota
    temperature: 0.2

  ollama:                                   # Optional — for users with local GPU
    base_url: "http://localhost:11434"
    model: "llama3.1:8b"
    temperature: 0.2

# Multi-provider agent assignment — distributes load across free tiers
agent_models:
  pm_agent: "groq_small"                   # Llama 3.1 8B — task breakdown is simple
  architect_agent: "groq"                   # Llama 3.3 70B — needs strong reasoning
  developer_agent: "groq"                   # Llama 3.3 70B — needs best code generation
  reviewer_agent: "gemini"                  # Gemini 2.5 Flash — separate token pool
  tester_agent: "gemini"                    # Gemini 2.5 Flash — separate token pool

workspace:
  output_dir: "./output"
  max_review_iterations: 3

# Docker sandbox — isolates agent shell commands in a throwaway container
# Falls back to direct host execution if Docker is unavailable
sandbox:
  enabled: true
```

**Required API keys** (`.env`):
```
GROQ_API_KEY=gsk_...          # From console.groq.com (free, no credit card)
GOOGLE_API_KEY=AI...           # From aistudio.google.com (free, no credit card)
```
