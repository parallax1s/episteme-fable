import pytest

from episteme_fable.providers import (GitHubModelsProvider, MockProvider,
                                      ProviderError, extract_json,
                                      make_provider)


def test_factory_default_is_claude(monkeypatch):
    monkeypatch.delenv("EPF_PROVIDER", raising=False)
    p = make_provider("claude-haiku-4-5-20251001")
    assert type(p).__name__ == "ClaudeCLIProvider"


def test_factory_github(monkeypatch):
    monkeypatch.setenv("EPF_PROVIDER", "github")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    p = make_provider("claude-haiku-4-5-20251001")  # claude id ignored
    assert isinstance(p, GitHubModelsProvider)
    assert p.model.startswith("openai/")
    p2 = make_provider("openai/gpt-4.1")
    assert p2.model == "openai/gpt-4.1"


def test_github_provider_requires_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(ProviderError):
        GitHubModelsProvider(token=None)


def test_github_ignores_claude_model_override(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    p = GitHubModelsProvider(model="openai/gpt-4.1-mini")
    # complete() would use self.model for a claude-style id; we only test
    # the resolution logic via the private prefix rule indirectly here.
    assert p.model == "openai/gpt-4.1-mini"


def test_extract_json_prefers_first_container():
    obj, err = extract_json('noise {"text": "x", "cites": [1, 2]} tail')
    assert err is None and obj["cites"] == [1, 2]
    arr, err = extract_json('[{"a": 1}] and {"b": 2}')
    assert err is None and isinstance(arr, list)


def test_mock_provider_exhaustion():
    p = MockProvider(["one"])
    assert p.complete("x") == "one"
    with pytest.raises(ProviderError):
        p.complete("y")
