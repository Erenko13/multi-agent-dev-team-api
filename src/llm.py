from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from src.config import AppConfig, ProviderConfig


def create_llm(provider: ProviderConfig) -> BaseChatModel:
    """Create an LLM instance from a provider configuration."""
    ptype = provider.provider_type

    if ptype in ("groq", "groq_small"):
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=provider.model,
            api_key=provider.api_key,
            temperature=provider.temperature,
            max_tokens=provider.max_tokens,
        )

    if ptype == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=provider.model,
            google_api_key=provider.api_key,
            temperature=provider.temperature,
            max_output_tokens=provider.max_tokens,
        )

    if ptype == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=provider.model,
            base_url=provider.base_url or "http://localhost:11434",
            temperature=provider.temperature,
        )

    if ptype == "openai_compatible":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=provider.model,
            base_url=provider.base_url,
            api_key=provider.api_key or "not-needed",
            temperature=provider.temperature,
            max_tokens=provider.max_tokens,
        )

    raise ValueError(f"Unknown provider type: {ptype}")


def get_llm_for_agent(agent_name: str, config: AppConfig) -> BaseChatModel:
    """Get the LLM for a specific agent, respecting per-agent overrides."""
    override = config.agent_overrides.get(agent_name)
    provider = override if override is not None else config.default_provider
    return create_llm(provider)
