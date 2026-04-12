from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class ProviderConfig:
    provider_type: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.2
    max_tokens: int | None = None


@dataclass
class AppConfig:
    default_provider: ProviderConfig
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    agent_overrides: dict[str, ProviderConfig | None] = field(default_factory=dict)
    output_dir: str = "./output"
    max_review_iterations: int = 3
    use_sandbox: bool = True


ENV_KEY_MAP = {
    "groq": "GROQ_API_KEY",
    "groq_small": "GROQ_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "together": "TOGETHER_API_KEY",
}


def load_config(config_path: str = "config.yaml") -> AppConfig:
    load_dotenv()

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    providers: dict[str, ProviderConfig] = {}
    for name, pconf in raw.get("providers", {}).items():
        env_var = ENV_KEY_MAP.get(name)
        api_key = pconf.get("api_key") or (os.getenv(env_var) if env_var else None)
        providers[name] = ProviderConfig(
            provider_type=name,
            model=pconf["model"],
            base_url=pconf.get("base_url"),
            api_key=api_key,
            temperature=pconf.get("temperature", 0.2),
            max_tokens=pconf.get("max_tokens"),
        )

    default_name = raw.get("default_provider", "groq")
    default_provider = providers[default_name]

    agent_overrides: dict[str, ProviderConfig | None] = {}
    for agent_name, provider_name in raw.get("agent_models", {}).items():
        if provider_name is not None and provider_name in providers:
            agent_overrides[agent_name] = providers[provider_name]
        else:
            agent_overrides[agent_name] = None

    workspace = raw.get("workspace", {})
    sandbox = raw.get("sandbox", {})

    return AppConfig(
        default_provider=default_provider,
        providers=providers,
        agent_overrides=agent_overrides,
        output_dir=workspace.get("output_dir", "./output"),
        max_review_iterations=workspace.get("max_review_iterations", 3),
        use_sandbox=sandbox.get("enabled", True),
    )
