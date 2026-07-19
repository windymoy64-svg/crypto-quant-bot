"""Factories for optional per-agent LLM clients."""

from __future__ import annotations

from app.llm.client import LLMClientConfig, OpenAICompatibleClient
from app.settings.llm_preferences import load_llm_api_key, load_llm_preferences


def build_agent_llm(agent: str):
    prefs = load_llm_preferences()
    model = prefs.agent_models.get(agent)
    api_key = load_llm_api_key()
    if not model or not prefs.base_url or not api_key:
        return None, None, prefs.base_url
    return (
        OpenAICompatibleClient(LLMClientConfig(
            base_url=prefs.base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=prefs.timeout_seconds,
        )),
        model,
        prefs.base_url,
    )