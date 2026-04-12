from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.agents.architect import architect_node
from src.agents.developer import developer_node
from src.agents.pm import pm_node
from src.agents.reviewer import reviewer_node
from src.agents.tester import tester_node
from src.config import AppConfig
from src.state import AgentState

if TYPE_CHECKING:
    from src.utils.container import DockerSandbox


def human_approve_architecture(state: AgentState) -> dict:
    """Interrupt for human to approve or revise architecture."""
    decision = interrupt({
        "type": "architecture_review",
        "architecture_doc": state.get("architecture_doc", ""),
        "tech_stack": state.get("tech_stack", {}),
        "folder_structure": state.get("folder_structure", []),
    })

    if decision.get("approved", False):
        return {"architecture_approved": True}
    else:
        feedback = decision.get("feedback", "Please revise the architecture.")
        return {
            "architecture_approved": False,
            "messages": [
                HumanMessage(content=f"Architecture revision requested: {feedback}")
            ],
        }


def human_approve_final(state: AgentState) -> dict:
    """Interrupt for human to approve or reject final output."""
    decision = interrupt({
        "type": "final_review",
        "generated_files": [f["path"] for f in state.get("generated_files", [])],
        "test_results": state.get("test_results", []),
        "tests_passing": state.get("tests_passing", False),
    })

    if decision.get("approved", False):
        return {"final_approved": True}
    else:
        return {"final_approved": False}


def route_after_architecture_approval(state: AgentState) -> str:
    if state.get("architecture_approved", False):
        return "developer_agent"
    return "architect_agent"


def route_after_review(state: AgentState) -> str:
    if state.get("review_approved", False):
        return "tester_agent"
    if state.get("review_iteration", 0) >= state.get("_max_review_iterations", 3):
        return "tester_agent"
    return "developer_agent"


def route_after_final_approval(state: AgentState) -> str:
    if state.get("final_approved", False):
        return END
    return "developer_agent"


def build_graph(config: AppConfig, sandbox: DockerSandbox | None = None) -> StateGraph:
    """Build the multi-agent development team graph."""

    # Bind config (and sandbox for agents that run shell commands) via partial
    pm = partial(pm_node, config=config)
    architect = partial(architect_node, config=config)
    developer = partial(developer_node, config=config, sandbox=sandbox)
    reviewer = partial(reviewer_node, config=config)
    tester = partial(tester_node, config=config, sandbox=sandbox)

    builder = StateGraph(AgentState)

    # Add nodes
    builder.add_node("pm_agent", pm)
    builder.add_node("architect_agent", architect)
    builder.add_node("human_approve_architecture", human_approve_architecture)
    builder.add_node("developer_agent", developer)
    builder.add_node("reviewer_agent", reviewer)
    builder.add_node("tester_agent", tester)
    builder.add_node("human_approve_final", human_approve_final)

    # Add edges
    builder.add_edge(START, "pm_agent")
    builder.add_edge("pm_agent", "architect_agent")
    builder.add_edge("architect_agent", "human_approve_architecture")

    builder.add_conditional_edges(
        "human_approve_architecture",
        route_after_architecture_approval,
        {"developer_agent": "developer_agent", "architect_agent": "architect_agent"},
    )

    builder.add_edge("developer_agent", "reviewer_agent")

    builder.add_conditional_edges(
        "reviewer_agent",
        route_after_review,
        {"tester_agent": "tester_agent", "developer_agent": "developer_agent"},
    )

    builder.add_edge("tester_agent", "human_approve_final")

    builder.add_conditional_edges(
        "human_approve_final",
        route_after_final_approval,
        {END: END, "developer_agent": "developer_agent"},
    )

    return builder


def compile_graph(config: AppConfig, sandbox: DockerSandbox | None = None):
    """Build and compile the graph with a memory checkpointer."""
    builder = build_graph(config, sandbox=sandbox)
    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)
