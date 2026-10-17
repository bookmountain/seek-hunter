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
    assert msgs[0].startswith("🎯 SeekHunter · 15 new (13:00)")
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


def test_digest_header_includes_extra_in_count():
    msgs = format_digest(
        [item(i) for i in range(10)], datetime(2026, 10, 17, 13, 0), "https://sh", [], extra=5
    )
    assert msgs[0].startswith("🎯 SeekHunter · 15 new (13:00)")


def test_digest_packs_long_items_under_telegram_limit():
    long_items = [
        DigestItem(job_id=200 + i, score=70, title="T" * 150, company="Acme", location="Adelaide SA",
                   work_type="contract", matched=["React", "TypeScript"], why="Strong match",
                   url="https://example.com/" + "u" * 200, flags=["flexible"])
        for i in range(10)
    ]
    msgs = format_digest(long_items, datetime(2026, 10, 17, 13, 0), "https://sh", [])
    assert len(msgs) > 1
    assert all(len(m) <= 4096 for m in msgs)


def test_unknown_work_type_falls_back_to_type_na():
    it = item(1, flags=())
    it.work_type = "internship"
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "Type n/a" in msgs[0]


def test_recap_format():
    msgs = format_recap([item(1), item(2, score=60)], excluded=4, day="Sat 17 Oct", public_url="https://sh")
    assert msgs[0].startswith("🎯 SeekHunter daily recap · Sat 17 Oct")
    assert "2 new jobs · 4 excluded" in msgs[0]


def test_recap_returns_list():
    msgs = format_recap([item(1)], excluded=0, day="Sat 17 Oct", public_url="https://sh")
    assert isinstance(msgs, list)


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
