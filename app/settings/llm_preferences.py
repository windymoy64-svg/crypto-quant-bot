"""LLM provider and per-agent model preferences.

All LLM usage is optional.  A model value of ``None``/``"none"`` means the
agent must run exactly as the deterministic implementation does today.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.settings.store import SecretsStore, get_secrets_store


AGENTS: tuple[str, ...] = ("chart", "learning", "decision", "executor")
_BASE_URL_KEY = "llm.base_url"
_API_KEY_KEY = "llm.api_key"
_TIMEOUT_KEY = "llm.timeout_seconds"
_MODELS_KEY = "llm.models"
_AGENT_MODEL_PREFIX = "llm.agent."


@dataclass(frozen=True)
class LLMPreferences:
    base_url: str = ""
    api_key_configured: bool = False
    api_key_masked: str = ""
    timeout_seconds: int = 30
    models: list[str] = field(default_factory=list)
    agent_models: dict[str, str | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "base_url": self.base_url,
            "api_key_configured": self.api_key_configured,
            "api_key_masked": self.api_key_masked,
            "timeout_seconds": self.timeout_seconds,
            "models": list(self.models),
            "agent_models": dict(self.agent_models),
            "agents": list(AGENTS),
        }


def load_llm_preferences(store: SecretsStore | None = None) -> LLMPreferences:
    store = store or get_secrets_store()
    api_key = store.get(_API_KEY_KEY) or ""
    models_raw = store.get(_MODELS_KEY) or ""
    models = [m for m in (item.strip() for item in models_raw.split("\n")) if m]
    agent_models = {
        agent: _normalize_model(store.get(f"{_AGENT_MODEL_PREFIX}{agent}.model"))
        for agent in AGENTS
    }
    return LLMPreferences(
        base_url=(store.get(_BASE_URL_KEY) or "").strip(),
        api_key_configured=bool(api_key),
        api_key_masked=_mask(api_key),
        timeout_seconds=_as_timeout(store.get(_TIMEOUT_KEY)),
        models=models,
        agent_models=agent_models,
    )


def load_llm_api_key(store: SecretsStore | None = None) -> str | None:
    return (store or get_secrets_store()).get(_API_KEY_KEY)


def save_llm_provider(
    *,
    base_url: str,
    api_key: str | None = None,
    timeout_seconds: int | None = None,
    store: SecretsStore | None = None,
) -> LLMPreferences:
    store = store or get_secrets_store()
    cleaned_url = str(base_url or "").strip().rstrip("/")
    if cleaned_url:
        store.set(_BASE_URL_KEY, cleaned_url)
    else:
        store.delete(_BASE_URL_KEY)
    if api_key is not None:
        cleaned_key = str(api_key or "").strip()
        if cleaned_key:
            store.set(_API_KEY_KEY, cleaned_key)
        else:
            store.delete(_API_KEY_KEY)
    if timeout_seconds is not None:
        store.set(_TIMEOUT_KEY, str(max(1, min(int(timeout_seconds), 120))))
    return load_llm_preferences(store)


def save_llm_models(models: list[str], store: SecretsStore | None = None) -> LLMPreferences:
    store = store or get_secrets_store()
    unique: list[str] = []
    for model in models:
        item = str(model or "").strip()
        if item and item not in unique:
            unique.append(item)
    if unique:
        store.set(_MODELS_KEY, "\n".join(unique))
    else:
        store.delete(_MODELS_KEY)
    return load_llm_preferences(store)


def save_agent_models(
    agent_models: dict[str, object], store: SecretsStore | None = None
) -> LLMPreferences:
    store = store or get_secrets_store()
    for agent in AGENTS:
        value = _normalize_model(agent_models.get(agent))
        key = f"{_AGENT_MODEL_PREFIX}{agent}.model"
        if value is None:
            store.delete(key)
        else:
            store.set(key, value)
    return load_llm_preferences(store)


def clear_llm_provider(store: SecretsStore | None = None) -> LLMPreferences:
    store = store or get_secrets_store()
    store.delete_many([_BASE_URL_KEY, _API_KEY_KEY, _TIMEOUT_KEY, _MODELS_KEY])
    for agent in AGENTS:
        store.delete(f"{_AGENT_MODEL_PREFIX}{agent}.model")
    return load_llm_preferences(store)


def _normalize_model(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"none", "null", "off", "disabled"}:
        return None
    return raw


def _as_timeout(value: str | None) -> int:
    try:
        return max(1, min(int(value or 30), 120))
    except (TypeError, ValueError):
        return 30


def _mask(value: str, *, keep: int = 4) -> str:
    if not value:
        return ""
    return "*" * max(0, len(value) - keep) + value[-keep:]