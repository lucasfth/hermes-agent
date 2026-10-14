"""Saved custom-endpoint models remain selectable while discovery is offline."""
from __future__ import annotations

import socket

import pytest

from hermes_cli.model_switch import switch_model


@pytest.mark.parametrize("legacy", [False, True])
def test_saved_endpoint_model_switches_without_network(monkeypatch, legacy):
    def offline(*args, **kwargs):
        pytest.fail("Selecting a saved model must not wait for hostname resolution")

    monkeypatch.setattr(socket, "getaddrinfo", offline)
    monkeypatch.setenv("SAVED_RELAY_KEY", "test-key")
    entry = {
        "name": "saved-relay",
        "base_url": "https://saved-relay.invalid/v1",
        "api_mode": "chat_completions",
        "key_env": "SAVED_RELAY_KEY",
        "models": {"gpt-6.1-sol": {}},
        "models_discovered": True,
        "context_length": 128000,
    }
    config = {"custom_providers": [entry]} if legacy else {"providers": {"saved-relay": entry}}
    monkeypatch.setattr("hermes_cli.runtime_provider.load_config", lambda: config)
    result = switch_model(
        "gpt-6.1-sol", "openai-codex", "gpt-5.6-terra",
        explicit_provider="custom:saved-relay" if legacy else "saved-relay",
        user_providers=config.get("providers", {}),
        custom_providers=config.get("custom_providers", []),
    )
    assert result.success, result.error_message
    assert result.new_model == "gpt-6.1-sol"
    assert result.base_url == entry["base_url"]
    assert result.api_key == "test-key"


def test_saved_generation_model_is_still_rejected(monkeypatch):
    monkeypatch.setenv("SAVED_RELAY_KEY", "test-key")
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda **kw: {})
    result = switch_model(
        "gpt-image-1.5", "openai-codex", "gpt-5.6-terra",
        explicit_provider="saved-relay",
        user_providers={"saved-relay": {
            "base_url": "https://saved-relay.invalid/v1",
            "api_mode": "chat_completions",
            "key_env": "SAVED_RELAY_KEY",
            "models": {"gpt-image-1.5": {}},
        }},
    )
    assert not result.success
    assert result.new_model == "gpt-image-1.5"
