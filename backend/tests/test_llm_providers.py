import json
import subprocess
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from seekhunter.llm.anthropic_provider import AnthropicProvider
from seekhunter.llm.base import BatchFit, JobFit, LLMJobInput, LLMUnavailable
from seekhunter.llm.openclaw_provider import OpenClawProvider
from seekhunter.profile import Profile

PROFILE = Profile(skills=set(), summary="s", titles=[], skill_lines=[], bullets=[])
JOBS = [LLMJobInput(key="1", title="Dev", company="A", work_type="contract", text="React")]


class FakeMessages:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.kwargs = result, error, None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(parsed_output=self.result)


def test_anthropic_success_uses_haiku_and_schema():
    msgs = FakeMessages(result=BatchFit(results=[JobFit(key="1", fit=80, why="React match")]))
    p = AnthropicProvider("k", client=SimpleNamespace(messages=msgs))
    out = p.score_batch(PROFILE, JOBS)
    assert out["1"].fit == 80
    assert msgs.kwargs["model"] == "claude-haiku-4-5"
    assert msgs.kwargs["output_format"] is BatchFit


def test_anthropic_api_error_becomes_unavailable():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIStatusError("credit balance too low", response=httpx.Response(400, request=req), body=None)
    p = AnthropicProvider("k", client=SimpleNamespace(messages=FakeMessages(error=err)))
    with pytest.raises(LLMUnavailable):
        p.score_batch(PROFILE, JOBS)


def test_openclaw_parses_envelope(monkeypatch):
    envelope = {"status": "ok", "result": {"meta": {
        "finalAssistantVisibleText": '{"results": [{"key": "1", "fit": 60, "why": "ok"}]}'}}}
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="log line\n" + json.dumps(envelope), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = OpenClawProvider("openclaw").score_batch(PROFILE, JOBS)
    assert out["1"].fit == 60
    assert captured["cmd"][:4] == ["openclaw", "agent", "--agent", "main"]
    assert "--json" in captured["cmd"]


def test_openclaw_failure_becomes_unavailable(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    with pytest.raises(LLMUnavailable):
        OpenClawProvider("openclaw").score_batch(PROFILE, JOBS)
