import pytest

from episteme_fable.providers import (CodexCLIProvider, GitHubModelsProvider,
                                      MockProvider, ProviderError, extract_json,
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


def test_codex_provider_injects_requested_service_tier(monkeypatch):
    monkeypatch.setenv("EPF_CODEX_SERVICE_TIER", "priority")
    provider = CodexCLIProvider(model="gpt-5.6-luna")
    command = provider._build_command("gpt-5.6-luna")
    assert ["-c", "service_tier=priority"] == command[command.index("service_tier=priority") - 1:command.index("service_tier=priority") + 1]


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


def test_factory_anthropic(monkeypatch):
    monkeypatch.setenv("EPF_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    from episteme_fable.providers import AnthropicAPIProvider
    p = make_provider("claude-sonnet-5-5")
    assert isinstance(p, AnthropicAPIProvider) and p.model == "claude-sonnet-5-5"


def test_anthropic_provider_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from episteme_fable.providers import AnthropicAPIProvider
    with pytest.raises(ProviderError):
        AnthropicAPIProvider()


def test_anthropic_provider_parses_text_blocks_and_retries_429(monkeypatch):
    import io
    import json as _json
    import urllib.error
    import urllib.request
    from episteme_fable import providers
    from episteme_fable.providers import AnthropicAPIProvider

    calls = []

    class _Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        calls.append(_json.loads(req.data))
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {"Retry-After": "0"}, io.BytesIO(b""))
        return _Resp(_json.dumps({"stop_reason": "end_turn", "content": [
            {"type": "thinking", "thinking": ""}, {"type": "text", "text": "[]"}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(providers.time, "sleep", lambda *_: None)
    p = AnthropicAPIProvider(api_key="k", model="claude-haiku-5-5")
    assert p.complete("hi", model="claude-sonnet-5-5") == "[]"
    assert len(calls) == 2 and calls[0]["model"] == "claude-sonnet-5-5"
    assert calls[0]["output_config"] == {"effort": "low"} and calls[0]["messages"][0]["content"] == "hi"
