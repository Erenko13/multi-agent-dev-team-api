from __future__ import annotations

import json
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.config import AppConfig
from src.llm import get_llm_for_agent
from src.prompts.tester import SYSTEM_PROMPT
from src.state import AgentState, FileOutput, TestResult
from src.tools.file_io import make_file_tools
from src.tools.shell import make_shell_tool

if TYPE_CHECKING:
    from src.utils.container import DockerSandbox


def tester_node(state: AgentState, config: AppConfig, sandbox: DockerSandbox | None = None) -> dict:
    """Tester agent: writes tests and runs them."""
    llm = get_llm_for_agent("tester_agent", config)
    workspace_path = state["workspace_path"]

    # Create tools scoped to workspace (shell runs inside sandbox if available)
    write_file, read_file, list_directory = make_file_tools(workspace_path)
    run_shell_command = make_shell_tool(workspace_path, sandbox=sandbox)

    tools = [write_file, read_file, list_directory, run_shell_command]
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    # Build context
    file_listing = "\n\n".join(
        f"### {f['path']}\n```{f['language']}\n{f['content']}\n```"
        for f in state.get("generated_files", [])
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"## Architecture\n{state.get('architecture_doc', 'N/A')}\n\n"
                f"## Source Files\n{file_listing}\n\n"
                f"## Tech Stack\n{json.dumps(state.get('tech_stack', {}), indent=2)}"
            )
        ),
    ]

    # Tool-calling loop
    for _ in range(20):
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
        parsed = {
            "test_files": [],
            "test_results": [{
                "test_file": "unknown",
                "passed": False,
                "output": f"Tester output could not be parsed: {content[:300]}",
            }],
            "tests_passing": False,
        }

    test_files = [
        FileOutput(path=f["path"], content=f.get("content", ""), language=f.get("language", ""))
        for f in parsed.get("test_files", [])
    ]
    test_results = [
        TestResult(test_file=r["test_file"], passed=r.get("passed", False), output=r.get("output", ""))
        for r in parsed.get("test_results", [])
    ]

    return {
        "test_files": test_files,
        "test_results": test_results,
        "tests_passing": parsed.get("tests_passing", False),
        "current_agent": "tester_agent",
        "messages": [
            AIMessage(
                content=f"Tester Agent completed: {len(test_files)} test files, passing: {parsed.get('tests_passing', False)}"
            )
        ],
    }
