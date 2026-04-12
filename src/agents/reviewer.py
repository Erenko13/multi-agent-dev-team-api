from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.config import AppConfig
from src.llm import get_llm_for_agent
from src.prompts.reviewer import SYSTEM_PROMPT
from src.state import AgentState
from src.tools.file_io import make_file_tools
from src.tools.search import make_search_tool


def reviewer_node(state: AgentState, config: AppConfig) -> dict:
    """Reviewer agent: reviews code, produces comments, approves or rejects."""
    llm = get_llm_for_agent("reviewer_agent", config)
    workspace_path = state["workspace_path"]

    # Create tools scoped to workspace
    _, read_file, list_directory = make_file_tools(workspace_path)
    search_codebase = make_search_tool(workspace_path)

    tools = [read_file, list_directory, search_codebase]
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    # Build context with all generated files
    file_listing = "\n\n".join(
        f"### {f['path']}\n```{f['language']}\n{f['content']}\n```"
        for f in state.get("generated_files", [])
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"## Architecture Spec\n{state.get('architecture_doc', 'N/A')}\n\n"
                f"## Files to Review\n{file_listing}"
            )
        ),
    ]

    # Tool-calling loop (reviewer may want to search/read files)
    for _ in range(10):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_fn = tool_map.get(tool_name)

            if tool_fn is None:
                messages.append(ToolMessage(
                    content=f"Error: Unknown tool: {tool_name}",
                    tool_call_id=tool_call["id"],
                ))
                continue

            try:
                result = tool_fn.invoke(tool_args)
            except Exception as e:
                result = f"Error: {e}"

            messages.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            ))

    # Parse the final response
    content = response.content
    try:
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        parsed = json.loads(content.strip())
    except (json.JSONDecodeError, IndexError):
        # If parsing fails, treat as not approved with a generic comment
        parsed = {
            "review_comments": [{
                "file_path": "general",
                "line_range": "N/A",
                "severity": "major",
                "comment": f"Reviewer output could not be parsed: {content[:300]}",
            }],
            "approved": False,
        }

    iteration = state.get("review_iteration", 0) + 1
    approved = parsed.get("approved", False)

    comments = parsed.get("review_comments", [])
    status = "APPROVED" if approved else f"{len(comments)} comments"

    return {
        "review_comments": comments,
        "review_approved": approved,
        "review_iteration": iteration,
        "current_agent": "reviewer_agent",
        "messages": [
            AIMessage(content=f"Review iteration {iteration}: {status}")
        ],
    }
