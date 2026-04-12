from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.config import AppConfig
from src.llm import get_llm_for_agent
from src.prompts.architect import SYSTEM_PROMPT
from src.state import AgentState


def architect_node(state: AgentState, config: AppConfig) -> dict:
    """Architect agent: designs system architecture from user stories and task plan."""
    llm = get_llm_for_agent("architect_agent", config)

    context = (
        f"## User Stories\n"
        + "\n".join(f"- {s}" for s in state.get("user_stories", []))
        + "\n\n## Task Plan\n"
        + json.dumps(state.get("task_plan", []), indent=2)
    )

    # If there's revision feedback from a rejected architecture, include it
    prev_messages = state.get("messages", [])
    feedback = ""
    for msg in reversed(prev_messages):
        if hasattr(msg, "content") and "Architecture revision requested" in msg.content:
            feedback = f"\n\n## Revision Feedback\n{msg.content}"
            break

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=context + feedback),
    ]

    response = llm.invoke(messages)
    content = response.content

    try:
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        parsed = json.loads(content.strip())
    except (json.JSONDecodeError, IndexError):
        return {
            "error": f"Architect agent failed to produce valid JSON: {content[:500]}",
            "current_agent": "architect_agent",
            "messages": [AIMessage(content="Architect Agent: Failed to parse output")],
        }

    return {
        "architecture_doc": parsed.get("architecture_doc", ""),
        "folder_structure": parsed.get("folder_structure", []),
        "tech_stack": parsed.get("tech_stack", {}),
        "current_agent": "architect_agent",
        "messages": [
            AIMessage(
                content=f"Architect Agent completed: {len(parsed.get('folder_structure', []))} files planned, stack: {parsed.get('tech_stack', {})}"
            )
        ],
    }
