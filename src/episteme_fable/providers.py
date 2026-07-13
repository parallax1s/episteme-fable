"""LLM transports. The engine only ever needs `complete(prompt) -> str`.

- ClaudeCLIProvider: shells out to `claude -p` (prompt on stdin, so argv
  length never matters). Retries with backoff on nonzero exit.
- MockProvider: a queue of canned responses, for tests and offline runs.

extract_json() is the total JSON reader: it never raises, returns
(value, error) and tolerates prose around the JSON and trailing commas.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import Any

DEFAULT_MODEL = os.environ.get("EPF_MODEL", "claude-haiku-4-5-20251001")
ASSEMBLE_MODEL = os.environ.get("EPF_MODEL_ASSEMBLE", "claude-sonnet-5")


class ProviderError(RuntimeError):
    pass


class ClaudeCLIProvider:
    def __init__(self, model: str = DEFAULT_MODEL, timeout: int = 240,
                 retries: int = 2):
        self.model = model
        self.timeout = timeout
        self.retries = retries

    def complete(self, prompt: str, model: str | None = None) -> str:
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                proc = subprocess.run(
                    ["claude", "-p", "--model", model or self.model],
                    input=prompt, capture_output=True, text=True,
                    timeout=self.timeout,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return proc.stdout.strip()
                last_err = ProviderError(
                    f"claude -p rc={proc.returncode}: {proc.stderr.strip()[:300]}")
            except (subprocess.TimeoutExpired, OSError) as e:
                last_err = e
            time.sleep(2 * (attempt + 1))
        raise ProviderError(f"provider failed after retries: {last_err}")


GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_DEFAULT_MODEL = os.environ.get("EPF_GITHUB_MODEL", "openai/gpt-4.1-mini")
_GH_MODEL_PREFIXES = ("openai/", "meta/", "mistral-ai/", "deepseek/",
                      "microsoft/", "cohere/", "xai/", "ai21-labs/", "core42/")


class GitHubModelsProvider:
    """Keyless-in-CI transport: the GitHub Models inference API, authed by
    GITHUB_TOKEN (a workflow's own token with `models: read`, or locally
    `gh auth token`). OpenAI-compatible chat completions; honors Retry-After
    on 429/5xx. Claude-style model ids passed by callers are ignored in
    favor of the provider's own catalog model."""

    def __init__(self, model: str = GITHUB_DEFAULT_MODEL, timeout: int = 180,
                 retries: int = 3, token: str | None = None):
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        if not self.token:
            raise ProviderError(
                "GitHubModelsProvider needs GITHUB_TOKEN "
                "(CI: the workflow token with models:read; local: gh auth token)")

    def complete(self, prompt: str, model: str | None = None) -> str:
        import urllib.error
        import urllib.request

        use_model = model if model and model.startswith(_GH_MODEL_PREFIXES) \
            else self.model
        body = json.dumps({
            "model": use_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            GITHUB_MODELS_URL, data=body, method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            })
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                if content and content.strip():
                    return content.strip()
                last_err = ProviderError("empty completion")
            except urllib.error.HTTPError as e:
                last_err = e
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if e.code in (429, 500, 502, 503) and attempt < self.retries:
                    try:
                        wait = min(float(retry_after or 5), 90.0)
                    except ValueError:
                        wait = 5.0
                    time.sleep(wait)
                    continue
                raise ProviderError(
                    f"GitHub Models HTTP {e.code}: {e.read().decode()[:200]}") from e
            except (OSError, KeyError, json.JSONDecodeError) as e:
                last_err = e
            time.sleep(2 * (attempt + 1))
        raise ProviderError(f"GitHub Models failed after retries: {last_err}")


def make_provider(model: str | None = None):
    """Provider factory: EPF_PROVIDER=claude (default) | github."""
    kind = os.environ.get("EPF_PROVIDER", "claude").lower()
    if kind == "github":
        if model and model.startswith(_GH_MODEL_PREFIXES):
            return GitHubModelsProvider(model=model)
        return GitHubModelsProvider()
    return ClaudeCLIProvider(model=model) if model else ClaudeCLIProvider()


class MockProvider:
    """Feed it responses in order; raises if the queue runs dry."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str, model: str | None = None) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise ProviderError("MockProvider queue exhausted")
        return self.responses.pop(0)


_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_SMART_QUOTES = str.maketrans({"“": '"', "”": '"',
                               "‘": "'", "’": "'"})


def _find_balanced(text: str, open_ch: str, close_ch: str) -> str | None:
    start = text.find(open_ch)
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        start = text.find(open_ch, start + 1)
    return None


def extract_json(text: str) -> tuple[Any, str | None]:
    """Pull the first JSON array (preferred) or object out of model text."""
    if text is None:
        return None, "empty response"
    # strip markdown fences first
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    # whichever container opens first wins — otherwise an array nested
    # inside an object (e.g. "cites": [1,2]) would shadow the object
    pairs = [("[", "]"), ("{", "}")]
    ai, oi = text.find("["), text.find("{")
    if oi != -1 and (ai == -1 or oi < ai):
        pairs.reverse()
    for open_ch, close_ch in pairs:
        candidate = _find_balanced(text, open_ch, close_ch)
        if candidate is None:
            continue
        for attempt in (candidate,
                        _TRAILING_COMMA.sub(r"\1", candidate),
                        _TRAILING_COMMA.sub(r"\1", candidate.translate(_SMART_QUOTES))):
            try:
                return json.loads(attempt), None
            except json.JSONDecodeError:
                continue
    return None, "no parseable JSON found"
