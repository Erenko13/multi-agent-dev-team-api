# Multi-Agent Dev Team API

A multi-agent software development team powered by **LangGraph** and **Python**, exposed as a **FastAPI REST API**. Five specialized AI agents collaborate to generate full-stack web applications from a natural language description.

Agents are distributed across **multiple free-tier LLM providers** (Groq, Google Gemini) to maximize daily throughput at zero cost.

## How It Works

You describe a web app in plain English. The agent pipeline handles the rest:

```
POST /api/projects  { "requirements": "Build a todo list app with FastAPI and React" }
        │
        ▼
   ┌─────────┐
   │ PM Agent │ ── Breaks requirements into user stories + task plan
   └────┬─────┘
        ▼
  ┌────────────┐
  │  Architect  │ ── Designs tech stack, folder structure, API design
  └─────┬──────┘
        ▼
 ★ APPROVAL CHECKPOINT ★  ◄── GET  /api/projects/{id}/approvals/pending
        │                      POST /api/projects/{id}/approvals
        ▼
  ┌────────────┐
  │  Developer  │ ── Writes all code files (tool-calling loop)
  └─────┬──────┘
        ▼
  ┌────────────┐
  │  Reviewer   │ ── Reviews code for bugs, security, quality
  └─────┬──────┘
        │
   approved? ──── No ──▶ back to Developer (max 3 iterations)
        │
       Yes
        ▼
  ┌────────────┐
  │   Tester   │ ── Writes and runs tests
  └─────┬──────┘
        ▼
 ★ APPROVAL CHECKPOINT ★  ◄── GET  /api/projects/{id}/approvals/pending
        │                      POST /api/projects/{id}/approvals
        ▼
     Done! ── Project files in ./output/{project_id}/
```

Real-time progress is streamed via **Server-Sent Events (SSE)** at `GET /api/projects/{id}/events`.

## Quick Start

### 1. Prerequisites

- Python 3.12+
- A free [Groq API key](https://console.groq.com) (no credit card required)
- A free [Google AI Studio API key](https://aistudio.google.com) (no credit card required)
- [Docker](https://docs.docker.com/get-docker/) (recommended, for sandboxed execution)

### 2. Install

```bash
git clone <repo-url>
cd multi-agent-dev-team-api
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Configure API Keys

```bash
cp .env.example .env
```

Edit `.env` and add your keys:

```
GROQ_API_KEY=gsk_your_key_here
GOOGLE_API_KEY=your_key_here
```

### 4. Run the API Server

```bash
uvicorn src.api.app:app --reload
```

The server starts at `http://localhost:8000`. Interactive API docs are available at `http://localhost:8000/docs`.

### 5. Run the CLI (alternative)

The original CLI is still available:

```bash
python -m src.main
```

You'll be prompted to describe the web app you want to build. The pipeline runs automatically, pausing at two human checkpoints for your approval.

---

## API Usage

### Start a Project

```bash
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{"requirements": "Build a todo list app with FastAPI and React"}'
```

Returns a `project_id` and status `running`.

### Stream Real-Time Events (SSE)

```bash
curl -N http://localhost:8000/api/projects/{project_id}/events
```

Events include `agent_completed`, `approval_required`, `pipeline_completed`, `pipeline_failed`.

### Check Project Status

```bash
curl http://localhost:8000/api/projects/{project_id}
```

Returns the full pipeline state: user stories, architecture, generated files, test results, and any pending approval.

### Submit an Approval

When the pipeline pauses for human review (architecture or final output):

```bash
# Approve
curl -X POST http://localhost:8000/api/projects/{project_id}/approvals \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'

# Reject with feedback
curl -X POST http://localhost:8000/api/projects/{project_id}/approvals \
  -H "Content-Type: application/json" \
  -d '{"approved": false, "feedback": "Use PostgreSQL instead of SQLite"}'
```

### List All Projects

```bash
curl http://localhost:8000/api/projects

# Filter by status
curl http://localhost:8000/api/projects?status=awaiting_approval
```

### Cancel a Project

```bash
curl -X DELETE http://localhost:8000/api/projects/{project_id}
```

### API Endpoints Summary

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Health check + Docker availability |
| `POST` | `/api/projects` | Start a new pipeline run |
| `GET` | `/api/projects` | List all sessions |
| `GET` | `/api/projects/{id}` | Get full project state |
| `GET` | `/api/projects/{id}/events` | SSE stream of real-time events |
| `GET` | `/api/projects/{id}/approvals/pending` | Check for pending approval |
| `POST` | `/api/projects/{id}/approvals` | Submit approval/rejection |
| `DELETE` | `/api/projects/{id}` | Cancel and clean up |

---

## Architecture

### Agentic Pattern: Supervisor Graph with Sequential Pipeline + Review Loop

The system uses a **LangGraph StateGraph** where each agent is a graph **node** and orchestration is handled by **conditional edges** — not by a separate supervisor LLM. This means routing decisions (who goes next) are deterministic and don't waste tokens on an LLM deciding the flow.

```
                ┌─────────────────────────────────────────────────┐
                │              LangGraph StateGraph                │
                │                                                  │
 User Input ──▶ │  ┌────┐    ┌───────────┐    ┌──────────────┐    │
                │  │ PM │───▶│ Architect │───▶│ HUMAN REVIEW │    │
                │  └────┘    └───────────┘    └──────┬───────┘    │
                │                                     │            │
                │                          ┌──── approve? ────┐   │
                │                          │ NO               │YES│
                │                          ▼                  ▼   │
                │                    ┌───────────┐    ┌─────────┐ │
                │                    │ Architect  │    │Developer│ │
                │                    │ (re-draft) │    └────┬────┘ │
                │                    └───────────┘         │      │
                │                                          ▼      │
                │                         ┌──────────────────┐    │
                │                         │     Reviewer      │    │
                │                         └────────┬─────────┘    │
                │                                  │              │
                │                     ┌──── approved? ────┐      │
                │                     │ NO (iter < 3)     │YES   │
                │                     ▼                    ▼      │
                │               ┌───────────┐      ┌────────┐    │
                │               │ Developer  │      │ Tester │    │
                │               │ (revision) │      └───┬────┘    │
                │               └───────────┘          │         │
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

### Why This Pattern

| Alternative | Why We Didn't Use It |
|---|---|
| **Supervisor agent** (LLM decides routing) | Wastes tokens on routing that's deterministic for our workflow |
| **Hierarchical multi-agent** (sub-teams) | Over-engineered for 5 agents — useful at 15+ |
| **Swarm / peer-to-peer** | No clear workflow — agents would duplicate work or deadlock |
| **CrewAI / AutoGen** | LangGraph gives finer control over state, routing, and human-in-the-loop |

### Three Core Principles

**1. Shared state, not message passing** — Agents don't talk to each other directly. They read from and write to a single `AgentState` dictionary that flows through the graph:

```
PM writes       → user_stories, task_plan
Architect reads → user_stories, task_plan
Architect writes → architecture_doc, tech_stack, folder_structure
Developer reads → architecture_doc, folder_structure, review_comments
Developer writes → generated_files
Reviewer reads  → generated_files, architecture_doc
Reviewer writes → review_comments, review_approved
Tester reads    → generated_files
Tester writes   → test_files, test_results
```

**2. Two agent patterns** — Pure reasoning agents (PM, Architect) make a single LLM call and return structured output. Tool-calling agents (Developer, Reviewer, Tester) run in a ReAct loop where the LLM iteratively calls tools until done.

**3. Graph-level routing** — Agents don't decide "who goes next." Conditional edges in the graph handle routing based on state fields (`review_approved`, `review_iteration`, `architecture_approved`).

---

## LLM Instance Model

Each agent gets its **own LLM instance** — a separate Python object with its own system prompt and (optionally) bound tools. They can share the same provider and API key, or use completely different providers.

```python
pm_llm        = ChatGroq(model="llama-3.1-8b-instant")         # lightweight
architect_llm = ChatGroq(model="llama-3.3-70b-versatile")      # strong reasoning
developer_llm = ChatGroq(model="llama-3.3-70b-versatile")      # best code gen
reviewer_llm  = ChatGoogleGenerativeAI(model="gemini-2.5-flash") # separate quota
tester_llm    = ChatGoogleGenerativeAI(model="gemini-2.5-flash") # separate quota
```

**No shared conversation history** between agents. Each agent starts fresh with only its system prompt + relevant state fields. The graph state is the shared memory, not the LLM context. This keeps token usage low and prevents prompt pollution.

---

## Multi-Provider Strategy

Agents are distributed across free-tier providers to maximize daily throughput:

| Agent | Provider | Model | Free Tier Limits |
|---|---|---|---|
| **PM** | Groq | Llama 3.1 8B Instant | 14,400 req/day, 500K tok/day |
| **Architect** | Groq | Llama 3.3 70B | 1,000 req/day, 100K tok/day |
| **Developer** | Groq | Llama 3.3 70B | (shared with Architect) |
| **Reviewer** | Google Gemini | 2.5 Flash | 250 req/day, 250K TPM |
| **Tester** | Google Gemini | 2.5 Flash | (shared with Reviewer) |

**Estimated capacity: ~3-4 full project runs per day** on free tiers alone.

You can change any agent's provider in `config.yaml`:

```yaml
agent_models:
  pm_agent: "groq_small"        # Llama 3.1 8B
  architect_agent: "groq"        # Llama 3.3 70B
  developer_agent: "groq"        # Llama 3.3 70B
  reviewer_agent: "gemini"       # Gemini 2.5 Flash
  tester_agent: "gemini"         # Gemini 2.5 Flash
```

Supported providers: `groq`, `groq_small`, `gemini`, `ollama`, `openai_compatible`.

---

## Checkpointing

A checkpoint is a serialized snapshot of the entire `AgentState` saved after every node executes. This enables:

| Purpose | How It Works |
|---|---|
| **Human-in-the-loop** | `interrupt()` pauses execution, saves state. The CLI resumes with your decision via `Command(resume=...)` |
| **Loop state preservation** | Developer-Reviewer loop: each iteration reads `review_comments` from the previous checkpoint |
| **Fault recovery** | If an agent crashes (API timeout, rate limit), re-invoke the graph and it resumes from the last checkpoint |

Uses `MemorySaver` (in-memory). Upgrade to `SqliteSaver` for persistence across process restarts.

---

## Agent Details

| Agent | Type | Tools | What It Does |
|---|---|---|---|
| **PM** | Pure reasoning | None | Breaks requirements into user stories and a prioritized task plan |
| **Architect** | Pure reasoning | None | Designs tech stack, folder structure, API endpoints, DB schema |
| **Developer** | Tool-calling (ReAct loop) | `write_file`, `read_file`, `list_directory`, `create_project_structure`, `run_shell_command` | Writes all code files, handles revisions from review |
| **Reviewer** | Tool-calling (ReAct loop) | `read_file`, `list_directory`, `search_codebase` | Reviews code for correctness, security, completeness |
| **Tester** | Tool-calling (ReAct loop) | `write_file`, `read_file`, `list_directory`, `run_shell_command` | Writes tests and executes them |

### Tool Safety

- All file tools are **sandboxed to the workspace directory** — path traversal is blocked
- `run_shell_command` uses an **allowlist** of safe command prefixes (`pip`, `npm`, `pytest`, `node`, etc.)
- Dangerous patterns (`rm -rf`, `sudo`, `curl`, `eval`) are blocked
- Developer-Reviewer loop is **hard-capped at 3 iterations**

---

## Docker Sandbox

By default, shell commands (`pip install`, `npm install`, `pytest`, etc.) execute inside a **throwaway Docker container** instead of directly on your host machine.

### How It Works

```
┌─────────────────────────────────────────────────┐
│  Your Host Machine                               │
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

- **File tools** (`write_file`, `read_file`) write to `./output/` on the host, which is bind-mounted into the container at `/workspace/`
- **Shell commands** (`pip install`, `npm test`, etc.) execute inside the container via `docker exec`
- The container has **Python 3.12 + Node.js 20** pre-installed
- Container is **created on pipeline start** and **destroyed when it finishes**
- Resource limits: 2 CPU cores, 2GB RAM

### Setup

Just have Docker installed and running. The sandbox image builds automatically on first run:

```bash
# First run builds the image (~30 seconds)
python -m src.main

# Output:
# Docker detected — starting sandbox container...
# Sandbox running: devteam-a3f8b2c1
```

### Disabling the Sandbox

If you don't want Docker isolation (or don't have Docker), set it in `config.yaml`:

```yaml
sandbox:
  enabled: false
```

The system falls back to direct host execution automatically if Docker is unavailable, even with `enabled: true`.

---

## Project Structure

```
multi-agent-dev-team-api/
├── pyproject.toml               # Package definition and dependencies
├── config.yaml                  # LLM provider and agent configuration
├── .env.example                 # Template for API keys
├── ARCHITECTURE.md              # Detailed implementation plan
├── sandbox/
│   └── Dockerfile               # Docker image for sandboxed execution
├── src/
│   ├── main.py                  # CLI entry point (Rich-based interactive)
│   ├── config.py                # YAML config loader
│   ├── llm.py                   # LLM factory (Groq/Gemini/Ollama/OpenAI-compat)
│   ├── state.py                 # AgentState TypedDict (shared graph state)
│   ├── graph.py                 # LangGraph StateGraph definition
│   ├── api/
│   │   ├── app.py               # FastAPI application, lifespan, CORS
│   │   ├── routes.py            # API endpoint definitions
│   │   ├── schemas.py           # Pydantic request/response models
│   │   ├── sessions.py          # SessionManager: pipeline lifecycle + approval bridge
│   │   └── dependencies.py      # FastAPI dependency injection
│   ├── agents/
│   │   ├── pm.py                # PM agent node
│   │   ├── architect.py         # Architect agent node
│   │   ├── developer.py         # Developer agent node (tool-calling loop)
│   │   ├── reviewer.py          # Reviewer agent node (tool-calling loop)
│   │   └── tester.py            # Tester agent node (tool-calling loop)
│   ├── tools/
│   │   ├── file_io.py           # write_file, read_file, list_directory
│   │   ├── shell.py             # run_shell_command (host or Docker)
│   │   ├── search.py            # search_codebase (regex across files)
│   │   └── project.py           # create_project_structure
│   ├── prompts/                 # System prompts per agent
│   └── utils/
│       ├── container.py         # DockerSandbox lifecycle manager
│       ├── output.py            # Rich console formatting
│       └── workspace.py         # Workspace directory management
└── tests/                       # 25 tests covering state, tools, and graph routing
```

---

## Configuration

### `config.yaml`

All LLM providers and agent assignments are configured here. Add new providers by defining them under `providers:` and assigning them to agents under `agent_models:`.

### Adding Ollama (local models)

If you have a GPU-capable machine:

```bash
# Install and start Ollama
ollama serve
ollama pull llama3.1:8b
```

Then update `config.yaml`:

```yaml
agent_models:
  developer_agent: "ollama"
```

### Adding a custom OpenAI-compatible endpoint

Works with LM Studio, vLLM, text-generation-webui, or any OpenAI-compatible server:

```yaml
providers:
  openai_compatible:
    base_url: "http://localhost:1234/v1"
    api_key: "not-needed"
    model: "your-model-name"
    temperature: 0.2
```

---

## Running Tests

```bash
source .venv/bin/activate
pip install pytest
pytest tests/ -v
```

---

## License

See [LICENSE](LICENSE).
