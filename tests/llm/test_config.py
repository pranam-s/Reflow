"""Tests for reflow.llm.config."""

import pytest

from reflow.llm.config import API_KEY_ENV_VAR, LlmConfig, load_api_key
from reflow.llm.errors import MissingApiKeyError


def test_load_api_key_reads_given_mapping() -> None:
    assert load_api_key({API_KEY_ENV_VAR: "sk-or-v1-test"}) == "sk-or-v1-test"


def test_load_api_key_raises_when_missing() -> None:
    with pytest.raises(MissingApiKeyError):
        load_api_key({})


def test_load_api_key_raises_when_empty() -> None:
    with pytest.raises(MissingApiKeyError):
        load_api_key({API_KEY_ENV_VAR: ""})


def test_load_api_key_reads_os_environ_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV_VAR, "sk-or-v1-env")
    assert load_api_key() == "sk-or-v1-env"


def test_llm_config_never_defaults_a_model() -> None:
    config = LlmConfig(model="deepseek/deepseek-v4-flash", api_key="k")
    assert config.model == "deepseek/deepseek-v4-flash"
    assert config.reasoning_effort is None


def test_llm_config_repr_never_exposes_the_api_key() -> None:
    config = LlmConfig(model="deepseek/deepseek-v4-flash", api_key="super-secret-value")
    assert "super-secret-value" not in repr(config)
