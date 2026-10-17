import json
import subprocess
from types import SimpleNamespace

import anthropic
import httpx
import pydantic
import pytest

from seekhunter.llm.anthropic_provider import AnthropicProvider
from seekhunter.llm.base import BatchFit, JobFit, LLMJobInput, LLMUnavailable
from seekhunter.llm.openclaw_provider import OpenClawProvider
from seekhunter.profile import Profile

PROFILE = Profile(skills=set(), summary="s", titles=[], skill_lines=[], bullets=[])
JOBS = [LLMJobInput(key="1", title="Dev", company="A", work_type="contract", text="React")]


def _envelope_stdout(fit=60):
    envelope = {"status": "ok", "result": {"meta": {
        "finalAssistantVisibleText": json.dumps({"results": [{"key": "1", "fit": fit, "why": "ok"}]})}}}
    return json.dumps(envelope)


class FakeMessages:
    def __init__(self, result=None, error=None, stop_reason="end_turn"):
        self.result, self.error, self.kwargs = result, error, None
        self.stop_reason = stop_reason

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(parsed_output=self.result, stop_reason=self.stop_reason)


def test_anthropic_success_uses_haiku_and_schema():
    msgs = FakeMessages(result=BatchFit(results=[JobFit(key="1", fit=80, why="React match")]))
    p = AnthropicProvider("k", client=SimpleNamespace(messages=msgs))
    out = p.score_batch(PROFILE, JOBS)
    assert out["1"].fit == 80
    assert msgs.kwargs["model"] == "claude-haiku-4-5"
    assert msgs.kwargs["output_format"] is BatchFit


def test_anthropic_api_error_becomes_unavailable():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIStatusError(
        "credit balance too low", response=httpx.Response(400, request=req), body=None
    )
    p = AnthropicProvider("k", client=SimpleNamespace(messages=FakeMessages(error=err)))
    with pytest.raises(LLMUnavailable):
        p.score_batch(PROFILE, JOBS)


def test_anthropic_validation_error_becomes_unavailable():
    try:
        pydantic.TypeAdapter(int).validate_python("x")
    except pydantic.ValidationError as e:
        err = e
    p = AnthropicProvider("k", client=SimpleNamespace(messages=FakeMessages(error=err)))
    with pytest.raises(LLMUnavailable):
        p.score_batch(PROFILE, JOBS)


def test_anthropic_max_tokens_stop_reason_becomes_unavailable():
    msgs = FakeMessages(
        result=BatchFit(results=[JobFit(key="1", fit=80, why="ok")]), stop_reason="max_tokens"
    )
    p = AnthropicProvider("k", client=SimpleNamespace(messages=msgs))
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
    assert captured["cmd"][:4] == ["openclaw", "agent", "--agent", "seekhunter-scorer"]
    assert "--json" in captured["cmd"]


def test_openclaw_failure_becomes_unavailable(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    with pytest.raises(LLMUnavailable):
        OpenClawProvider("openclaw").score_batch(PROFILE, JOBS)


def test_openclaw_uses_scorer_agent_in_cmd(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=_envelope_stdout(), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    OpenClawProvider("openclaw").score_batch(PROFILE, JOBS)
    assert "--agent" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--agent") + 1] == "seekhunter-scorer"


def test_openclaw_uses_fresh_session_id_each_call(monkeypatch):
    captured = []

    def fake_run(cmd, **kw):
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=_envelope_stdout(), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = OpenClawProvider("openclaw")
    provider.score_batch(PROFILE, JOBS)
    provider.score_batch(PROFILE, JOBS)

    def session_id(cmd):
        return cmd[cmd.index("--session-id") + 1]

    assert session_id(captured[0]) != session_id(captured[1])


def test_openclaw_oversized_prompt_raises_without_calling_subprocess(monkeypatch):
    def fail_run(cmd, **kw):
        raise AssertionError("subprocess.run should not be called for an oversized prompt")

    monkeypatch.setattr(subprocess, "run", fail_run)
    huge_jobs = [
        LLMJobInput(key=str(i), title="Dev", company="A", work_type="contract", text="x" * 3500)
        for i in range(40)
    ]
    with pytest.raises(LLMUnavailable):
        OpenClawProvider("openclaw").score_batch(PROFILE, huge_jobs)


def test_openclaw_handles_log_noise_before_envelope(monkeypatch):
    envelope = {"result": {"meta": {
        "finalAssistantVisibleText": '{"results": [{"key": "1", "fit": 60, "why": "ok"}]}'}}}
    noisy_stdout = "warning: {not json} happened\n" + json.dumps(envelope)

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=noisy_stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = OpenClawProvider("openclaw").score_batch(PROFILE, JOBS)
    assert out["1"].fit == 60


def test_openclaw_timeout_becomes_unavailable(monkeypatch):
    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 300)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(LLMUnavailable):
        OpenClawProvider("openclaw").score_batch(PROFILE, JOBS)
