import subprocess
from datetime import datetime

import pytest

from seekhunter.notify import DigestItem, Notifier, NotifyError, format_digest, format_recap


def item(i, score=80, flags=("flexible",)):
    return DigestItem(job_id=100 + i, score=score, title=f"Dev {i}", company="Acme", location="Adelaide SA",
                      work_type="contract", matched=["React", "TypeScript"], why="Strong React match",
                      url=f"https://www.seek.com.au/job/{i}", flags=list(flags))


def test_digest_format_and_split():
    msgs = format_digest(
        [item(i) for i in range(12)], datetime(2026, 10, 17, 13, 0), "https://sh", [], extra=3
    )
    assert len(msgs) == 2
    assert msgs[0].startswith("🎯 SeekHunter · 12 new (13:00)")
    assert "#100 [80] Dev 0 — Acme · Adelaide SA · Contract 💼" in msgs[0]
    assert "Reply to OpenClaw" in msgs[-1]
    assert "React, TypeScript ✓" in msgs[0]
    assert '"Strong React match"' in msgs[0]
    assert "+3 more" in msgs[-1]
    assert msgs[-1].rstrip().endswith("→ https://sh")


def test_digest_mentions_degraded_sources_and_hours_flag():
    msgs = format_digest([item(1, flags=("flexible", "hours"))], datetime(2026, 10, 17, 9, 0), "https://sh",
                         ["jora"])
    assert "⚠️ hours" in msgs[0]
    assert "jora unavailable this run" in msgs[0]


def test_recap_format():
    text = format_recap([item(1), item(2, score=60)], excluded=4, day="Sat 17 Oct", public_url="https://sh")
    assert text.startswith("🎯 SeekHunter daily recap · Sat 17 Oct")
    assert "2 new jobs · 4 excluded" in text


def test_notifier_invokes_openclaw(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    Notifier("openclaw", "123").send("hi")
    assert calls[0] == ["openclaw", "message", "send", "--channel", "telegram", "--target", "123",
                        "--message", "hi"]


def test_notifier_failure_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "nope"))
    with pytest.raises(NotifyError):
        Notifier("openclaw", "123").send("hi")


def test_notifier_dry_run_prints(capsys):
    Notifier("openclaw", "123", dry_run=True).send("hello")
    assert "hello" in capsys.readouterr().out
