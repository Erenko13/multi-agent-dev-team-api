from __future__ import annotations

import json
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.config import AppConfig
from src.llm import get_llm_for_agent
from src.prompts.developer import SYSTEM_PROMPT
from src.state import AgentState, FileOutput
from src.tools.file_io import make_file_tools
from src.tools.project import make_project_tool
from src.tools.shell import make_shell_tool

if TYPE_CHECKING:
    from src.utils.container import DockerSandbox


def _infer_language(path: str) -> str:
    ext_map = {
        ".py": "python", ".js": "javascript", ".jsx": "javascript",
        ".ts": "typescript", ".tsx": "typescript", ".html": "html",
        ".css": "css", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
        ".md": "markdown", ".sql": "sql", ".sh": "bash",
        ".toml": "toml", ".txt": "text", ".env": "env",
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return "text"


def developer_node(state: AgentState, config: AppConfig, sandbox: DockerSandbox | None = None) -> dict:
    """Developer agent: writes code files based on architecture. Uses tool-calling loop."""
    llm = get_llm_for_agent("developer_agent", config)
    workspace_path = state["workspace_path"]

    # Create tools scoped to workspace (shell runs inside sandbox if available)
    write_file, read_file, list_directory = make_file_tools(workspace_path)
    create_project_structure = make_project_tool(workspace_path)
    run_shell_command = make_shell_tool(workspace_path, sandbox=sandbox)

    tools = [write_file, read_file, list_directory, create_project_structure, run_shell_command]
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    # Build context
    context_parts = [
        f"## Architecture\n{state.get('architecture_doc', 'N/A')}",
        f"## Task Plan\n{json.dumps(state.get('task_plan', []), indent=2)}",
        f"## Folder Structure\n" + "\n".join(state.get("folder_structure", [])),
    ]
    if state.get("review_comments"):
        context_parts.append(
            f"## Review Comments to Address\n{json.dumps(state['review_comments'], indent=2)}"
        )
    if state.get("generated_files"):
        context_parts.append(
            f"## Previously Generated Files\n"
            + "\n".join(f["path"] for f in state["generated_files"])
        )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content="\n\n".join(context_parts)),
    ]

    # Tool-calling loop
    generated_files: list[FileOutput] = []
    written_paths: set[str] = set()

    for _ in range(30):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_fn = tool_map.get(tool_name)

            if tool_fn is None:
                from langchain_core.messages import ToolMessage
                messages.append(ToolMessage(
                    content=f"Error: Unknown tool: {tool_name}",
                    tool_call_id=tool_call["id"],
                ))
                continue

            try:
                result = tool_fn.invoke(tool_args)
            except Exception as e:
                result = f"Error: {e}"

            from langchain_core.messages import ToolMessage
            messages.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            ))

            # Track written files
            if tool_name == "write_file" and "path" in tool_args:
                path = tool_args["path"]
                content = tool_args.get("content", "")
                if path not in written_paths:
                    written_paths.add(path)
                    generated_files.append(FileOutput(
                        path=path,
                        content=content,
                        language=_infer_language(path),
                    ))
                else:
                    # Update existing entry
                    for i, f in enumerate(generated_files):
                        if f["path"] == path:
                            generated_files[i] = FileOutput(
                                path=path,
                                content=content,
                                language=_infer_language(path),
                            )
                            break

    return {
        "generated_files": generated_files,
        "current_agent": "developer_agent",
        "review_iteration": state.get("review_iteration", 0),
        "messages": [
            AIMessage(content=f"Developer Agent completed: wrote {len(generated_files)} files")
        ],
    }
