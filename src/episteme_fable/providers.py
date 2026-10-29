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


CODEX_DEFAULT_MODEL = os.environ.get("EPF_CODEX_MODEL", "gpt-5.6-luna")


class CodexCLIProvider:
    """`codex exec` on the user's ChatGPT subscription (OpenAI Codex CLI).
    Ported from antifragile-reader/pipeline/providers.py (the proven
    pattern): prompt on stdin, `--json` event stream read incrementally,
    the whole process group killed after EPF_CODEX_INACTIVITY seconds
    without an event or at the hard timeout (watchdog thread), so a wedged
    connection can never hang a pipeline. User config/rules/AGENTS.md are
    ignored so each call carries only our prompt; --ephemeral keeps the
    session store clean; sandbox read-only. Claude model ids passed by
    callers are ignored in favor of EPF_CODEX_MODEL (default gpt-5.6-luna);
    EPF_REASONING_EFFORT (default low) — higher efforts cost ~10x latency;
    EPF_CODEX_SERVICE_TIER optionally selects a model service tier (for
    example, ``priority`` for Luna Fast mode)."""

    def __init__(self, model: str | None = None, timeout: int = 420, retries: int = 2):
        self.model = model or CODEX_DEFAULT_MODEL
        self.effort = os.environ.get("EPF_REASONING_EFFORT", "low")
        self.service_tier = os.environ.get("EPF_CODEX_SERVICE_TIER")
        self.timeout, self.retries = timeout, retries
        self.workdir = os.path.join(
            os.environ.get("EPF_CODEX_WORKDIR", os.path.join(os.path.expanduser("~"), ".epf-codex-cwd")))
        os.makedirs(self.workdir, exist_ok=True)

    def resolve(self, model: str | None) -> str:
        if model and not model.startswith("claude"):
            return model
        return self.model

    def _build_command(self, model: str | None) -> list[str]:
        cmd = ["codex", "exec", "--json", "-m", self.resolve(model),
               "-c", f"model_reasoning_effort={self.effort}"]
        if self.service_tier:
            cmd.extend(["-c", f"service_tier={self.service_tier}"])
        cmd.extend(["-s", "read-only", "--skip-git-repo-check", "--ephemeral",
                    "--ignore-user-config", "--ignore-rules", "-C", self.workdir, "-"])
        return cmd

    def complete(self, prompt: str, model: str | None = None) -> str:
        import selectors
        import signal
        import threading
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        inactivity = float(os.environ.get("EPF_CODEX_INACTIVITY", "120"))
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            cmd = self._build_command(model)
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, env=env, cwd=self.workdir,
                                    start_new_session=True)

            def killpg():
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    try:
                        proc.kill()
                    except (ProcessLookupError, PermissionError):
                        pass

            watchdog = threading.Timer(self.timeout, killpg)
            watchdog.daemon = True
            watchdog.start()
            reply, reason = "", ""
            try:
                try:
                    proc.stdin.write(prompt.encode("utf-8"))
                    proc.stdin.close()
                except BrokenPipeError:
                    pass
                sel = selectors.DefaultSelector()
                sel.register(proc.stdout, selectors.EVENT_READ)
                deadline = time.time() + self.timeout
                last_event = time.time()
                buf = b""
                while True:
                    now = time.time()
                    if now > deadline:
                        reason = f"hard timeout {self.timeout}s"
                        break
                    if now - last_event > inactivity:
                        reason = f"no event for {inactivity:.0f}s"
                        break
                    if not sel.select(timeout=1.0):
                        if proc.poll() is not None:
                            break
                        continue
                    chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(65536)
                    if not chunk:
                        break
                    last_event = time.time()
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            ev = json.loads(line.decode("utf-8", "replace"))
                        except ValueError:
                            continue
                        item = ev.get("item") or {}
                        if ev.get("type") == "item.completed" and item.get("type") == "agent_message":
                            reply = (item.get("text") or "").strip()
                        elif ev.get("type") in ("turn.failed", "error"):
                            reason = f"codex event {ev.get('type')}: {json.dumps(ev)[:200]}"
                sel.close()
            finally:
                watchdog.cancel()
                killpg()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
            if reply and not reason:
                return reply
            last_err = ProviderError(reason or f"codex exec rc={proc.returncode}: no agent_message in stream")
            time.sleep(2 * (attempt + 1))
        raise ProviderError(f"codex provider failed after retries: {last_err}")


class FileQueueProvider:
    """No LLM at all: the *agents running this pipeline* are the model.

    complete(prompt) hashes the prompt, writes it to
    <EPF_QUEUE_DIR>/pending/<hash>.prompt.md, and then waits until
    <EPF_QUEUE_DIR>/done/<hash>.reply.txt exists, returning its contents.
    Sub-agents (human or LLM) drain pending/ by reading each prompt, producing
    the reply the prompt asks for (a JSON array for propose windows), and
    writing it to done/ under the same hash. Everything downstream — JSON
    extraction, validators, identity, assembly — is unchanged, so agent
    output is held to exactly the same contract as any API model's.

    Two modes via EPF_QUEUE_WAIT (seconds; default 0):
      0        -> "dump" mode: complete() raises QueuePending after writing
                  the prompt. The engine treats it as a failed window, the
                  doc is NOT cached, and a rerun after the queue is drained
                  picks up the replies. Use this to enqueue thousands of
                  prompts in one pass without blocking.
      N > 0    -> "block" mode: complete() polls for the reply up to N s.
    Identical prompts share one hash, so repair-round prompts (prompt +
    REPAIR_SUFFIX) get their own file and never collide with the original."""

    def __init__(self, queue_dir: str | None = None):
        import hashlib
        self._hashlib = hashlib
        self.queue_dir = queue_dir or os.environ.get("EPF_QUEUE_DIR", "epf_queue")
        self.wait = float(os.environ.get("EPF_QUEUE_WAIT", "0"))
        self.poll = float(os.environ.get("EPF_QUEUE_POLL", "2"))
        self.pending = os.path.join(self.queue_dir, "pending")
        self.done = os.path.join(self.queue_dir, "done")
        os.makedirs(self.pending, exist_ok=True)
        os.makedirs(self.done, exist_ok=True)

    def _key(self, prompt: str) -> str:
        return self._hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:24]

    def complete(self, prompt: str, model: str | None = None) -> str:
        key = self._key(prompt)
        reply_path = os.path.join(self.done, f"{key}.reply.txt")
        if os.path.exists(reply_path):
            text = open(reply_path, encoding="utf-8").read().strip()
            if text:
                return text
        prompt_path = os.path.join(self.pending, f"{key}.prompt.md")
        if not os.path.exists(prompt_path):
            tmp = prompt_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(prompt)
            os.replace(tmp, prompt_path)
        if self.wait <= 0:
            raise QueuePending(f"prompt queued: {prompt_path}")
        deadline = time.time() + self.wait
        while time.time() < deadline:
            if os.path.exists(reply_path):
                text = open(reply_path, encoding="utf-8").read().strip()
                if text:
                    return text
            time.sleep(self.poll)
        raise ProviderError(f"queue reply not produced within {self.wait:.0f}s: {reply_path}")


class QueuePending(ProviderError):
    """Raised in dump mode after a prompt has been written to the queue."""


def make_provider(model: str | None = None):
    """Provider factory: EPF_PROVIDER=claude (default) | github | codex | queue."""
    kind = os.environ.get("EPF_PROVIDER", "claude").lower()
    if kind == "queue":
        return FileQueueProvider()
    if kind == "github":
        if model and model.startswith(_GH_MODEL_PREFIXES):
            return GitHubModelsProvider(model=model)
        return GitHubModelsProvider()
    if kind == "codex":
        return CodexCLIProvider()
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
