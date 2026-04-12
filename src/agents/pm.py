from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.config import AppConfig
from src.llm import get_llm_for_agent
from src.prompts.pm import SYSTEM_PROMPT
from src.state import AgentState


def pm_node(state: AgentState, config: AppConfig) -> dict:
    """PM agent: takes user requirements, produces user stories and task plan."""
    llm = get_llm_for_agent("pm_agent", config)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Requirements:\n{state['user_requirements']}"),
    ]

    response = llm.invoke(messages)
    content = response.content

    # Parse JSON from response
    try:
        # Handle markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        parsed = json.loads(content.strip())
    except (json.JSONDecodeError, IndexError):
        return {
            "error": f"PM agent failed to produce valid JSON: {content[:500]}",
            "current_agent": "pm_agent",
            "messages": [AIMessage(content="PM Agent: Failed to parse output")],
        }

    user_stories = parsed.get("user_stories", [])
    task_plan = parsed.get("task_plan", [])

    return {
        "user_stories": user_stories,
        "task_plan": task_plan,
        "current_agent": "pm_agent",
        "messages": [
            AIMessage(
                content=f"PM Agent completed: {len(user_stories)} user stories, {len(task_plan)} tasks"
            )
        ],
    }
