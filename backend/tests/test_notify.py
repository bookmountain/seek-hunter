import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from seekhunter.notify import (
    DigestItem,
    Notifier,
    NotifyError,
    format_brief,
    format_digest,
    format_market_brief,
    format_recap,
)


def item(i, score=80, flags=("flexible",), location="Adelaide SA", why="Strong React match",
        matched=("React", "TypeScript"), url=None):
    return DigestItem(job_id=100 + i, score=score, title=f"Dev {i}", company="Acme", location=location,
                      work_type="contract", matched=list(matched), why=why,
                      url=url or f"https://www.seek.com.au/job/{i}", flags=list(flags))


def _no_disallowed_chars(text: str) -> bool:
    return all(ord(ch) <= 0x2500 or ch in "—·…" for ch in text)


def test_digest_format_and_split():
    msgs = format_digest(
        [item(i) for i in range(12)], datetime(2026, 10, 17, 13, 0), "https://sh", [], extra=3
    )
    assert len(msgs) == 2
    assert msgs[0].startswith("SeekHunter — 15 new, 12 flexible (13:00)")
    assert "#100 · 80 · Dev 0" in msgs[0]
    assert "Acme · Contract" in msgs[0]
    assert "Reply to OpenClaw: save 100 · hide 100 · why 100" in msgs[-1]
    assert '"Strong React match"' not in msgs[0]
    assert "Strong React match" in msgs[0]
    assert "+3 more: sh" in msgs[-1]
    assert msgs[-1].rstrip().endswith("why 100")


def test_digest_mentions_degraded_sources_and_hours_flag():
    msgs = format_digest([item(1, flags=("flexible", "hours"))], datetime(2026, 10, 17, 9, 0), "https://sh",
                         ["jora"])
    assert "hours?" in msgs[0]
    assert "Jora unavailable this run" in msgs[0]


def test_digest_header_includes_extra_in_count():
    msgs = format_digest(
        [item(i) for i in range(10)], datetime(2026, 10, 17, 13, 0), "https://sh", [], extra=5
    )
    assert msgs[0].startswith("SeekHunter — 15 new, 10 flexible (13:00)")


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


def test_blank_line_separates_job_blocks():
    msgs = format_digest([item(1), item(2)], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "#101" in msgs[0] and "#102" in msgs[0]
    first_block_end = msgs[0].index("#102")
    assert msgs[0][:first_block_end].endswith("\n\n")


def test_jora_url_is_shortened_to_id():
    hex_id = "0df32b6e859d734ba88f1b03a73a7b3d"
    it = item(1, url=f"https://au.jora.com/job/Developer-Programmer-SA-{hex_id}")
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert f"au.jora.com/job/j-{hex_id}" in msgs[0]
    assert "Developer-Programmer-SA" not in msgs[0]


def test_seek_url_drops_scheme_and_www():
    it = item(1, url="https://www.seek.com.au/job/95262793")
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "seek.com.au/job/95262793" in msgs[0]
    assert "https://" not in msgs[0]
    assert "www." not in msgs[0]


def test_generic_adelaide_location_is_omitted():
    it = item(1, location="Adelaide SA")
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "Adelaide SA" not in msgs[0]


def test_suburb_location_is_shortened_to_part_before_comma():
    it = item(1, location="Daw Park, Adelaide SA")
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "Daw Park" in msgs[0]
    assert "Adelaide SA" not in msgs[0]


def test_other_city_location_is_kept_in_full():
    it = item(1, location="Sydney NSW")
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "Sydney NSW" in msgs[0]


def test_llm_note_is_truncated_at_word_boundary():
    note = ("Java, Spring, React fit very well with the role but there is a notable Hibernate "
            "gap worth flagging")
    it = item(1, why=note)
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    lines = msgs[0].splitlines()
    note_line = next(line for line in lines if line.endswith("…"))
    assert len(note_line) <= 80
    assert not note_line[:-1].endswith(" ")
    assert note[: len(note_line) - 1].rstrip() == note_line[:-1]


def test_short_llm_note_is_not_truncated():
    it = item(1, why="Short fit note")
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "Short fit note" in msgs[0]
    assert "…" not in msgs[0]


def test_falls_back_to_matched_skills_when_no_note():
    it = item(1, why=None, matched=("React", "TypeScript", "Node", "SQL", "GraphQL"))
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "React, TypeScript, Node, SQL" in msgs[0]
    assert "GraphQL" not in msgs[0]


def test_note_line_omitted_when_no_note_and_no_matches():
    it = item(1, why=None, matched=())
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    lines = [line for line in msgs[0].splitlines() if line.strip()]
    job_lines = [line for line in lines if line.startswith("#101")]
    assert len(job_lines) == 1
    idx = lines.index(job_lines[0])
    # title line, meta line, then straight to the url (no note/skills line)
    assert lines[idx + 2].endswith("/job/1") or "seek.com.au" in lines[idx + 2]


def test_no_emoji_in_digest_or_recap():
    msgs = format_digest([item(i) for i in range(3)], datetime(2026, 10, 17, 9, 0), "https://sh", ["jora"])
    for m in msgs:
        assert _no_disallowed_chars(m)
    recap_msgs = format_recap([item(1)], excluded=2, day="Sat 17 Oct", public_url="https://sh")
    for m in recap_msgs:
        assert _no_disallowed_chars(m)


def test_recap_format():
    msgs = format_recap([item(1), item(2, score=60)], excluded=4, day="Sat 17 Oct", public_url="https://sh")
    assert msgs[0].startswith("SeekHunter daily recap — Sat 17 Oct")
    assert "2 new jobs, 4 excluded" in msgs[0]


def test_recap_returns_list():
    msgs = format_recap([item(1)], excluded=0, day="Sat 17 Oct", public_url="https://sh")
    assert isinstance(msgs, list)


def test_recap_caps_at_fifteen_items_and_notes_the_rest():
    msgs = format_recap([item(i) for i in range(20)], excluded=0, day="Sat 17 Oct", public_url="https://sh")
    assert "+5 more" in msgs[-1]


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


def test_digest_includes_contact_name_and_phone_line():
    it = item(1)
    it.contact_name, it.contact_phone = "Brayden Mackay", "08 8216 3534"
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "Brayden Mackay · 08 8216 3534" in msgs[0]


def test_digest_contact_line_uses_email_only_when_no_phone():
    it = item(1)
    it.contact_name, it.contact_email = "Brayden Mackay", "brayden@acme.com"
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "Brayden Mackay · brayden@acme.com" in msgs[0]


def test_digest_contact_line_prefers_phone_over_email():
    it = item(1)
    it.contact_name = "Brayden Mackay"
    it.contact_phone = "08 8216 3534"
    it.contact_email = "brayden@acme.com"
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "Brayden Mackay · 08 8216 3534" in msgs[0]
    assert "brayden@acme.com" not in msgs[0]


def test_digest_meta_line_includes_applicant_count_when_present():
    it = item(1, flags=())
    it.applicant_count = 77
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "Acme · Contract · 77 applicants" in msgs[0]


def test_digest_meta_line_omits_applicant_count_when_absent():
    it = item(1, flags=())
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "applicants" not in msgs[0]


def test_digest_meta_line_orders_applicants_after_hours_flag():
    it = item(1, flags=("hours",))
    it.applicant_count = 10
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    assert "Acme · Contract · hours? · 10 applicants" in msgs[0]


def test_digest_omits_contact_line_when_no_contact_info():
    it = item(1)
    msgs = format_digest([it], datetime(2026, 10, 17, 9, 0), "https://sh", [])
    lines = [line for line in msgs[0].splitlines() if line.strip()]
    job_idx = next(i for i, line in enumerate(lines) if line.startswith("#101"))
    assert lines[job_idx + 1] == "Acme · Contract"
    assert lines[job_idx + 2] == "Strong React match"


def test_format_brief_includes_recruiter_and_linkedin_lines():
    text = format_brief(
        job_id=7, title="React Dev", company="Acme", location="Adelaide SA", work_type="contract",
        salary="$90/h", score=80, rule_score=75, llm_score=88, llm_note="Strong React",
        matched=["React"], missing=["Kotlin"], flags=["flexible"], reasons=[], status="new",
        url="https://x/7", description="desc", contact_name="Brayden Mackay",
        contact_phone="08 8216 3534", contact_linkedin="https://www.linkedin.com/in/brayden-mackay",
    )
    assert "Recruiter: Brayden Mackay · 08 8216 3534" in text
    assert "LinkedIn: https://www.linkedin.com/in/brayden-mackay" in text


def test_format_brief_falls_back_to_search_url_when_no_linkedin_profile():
    text = format_brief(
        job_id=7, title="React Dev", company="Acme", location="Adelaide SA", work_type="contract",
        salary="$90/h", score=80, rule_score=75, llm_score=88, llm_note="Strong React",
        matched=["React"], missing=["Kotlin"], flags=["flexible"], reasons=[], status="new",
        url="https://x/7", description="desc", contact_name="Brayden Mackay",
        contact_search={"linkedin": "https://www.linkedin.com/search/results/people/?keywords=x"},
    )
    assert "LinkedIn: https://www.linkedin.com/search/results/people/?keywords=x" in text


def test_format_brief_includes_competition_line_when_present():
    text = format_brief(
        job_id=7, title="React Dev", company="Acme", location="Adelaide SA", work_type="contract",
        salary="$90/h", score=80, rule_score=75, llm_score=88, llm_note="Strong React",
        matched=["React"], missing=["Kotlin"], flags=["flexible"], reasons=[], status="new",
        url="https://x/7", description="desc", competition="77 applicants (Medium application volume) "
        "· 100% resume · 57% cover letter · checked 2026-10-17T09:00:00",
    )
    assert ("Competition: 77 applicants (Medium application volume) · 100% resume · 57% cover letter "
           "· checked 2026-10-17T09:00:00") in text


def test_format_brief_omits_competition_line_when_absent():
    text = format_brief(
        job_id=7, title="React Dev", company="Acme", location="Adelaide SA", work_type="contract",
        salary="$90/h", score=80, rule_score=75, llm_score=88, llm_note="Strong React",
        matched=["React"], missing=["Kotlin"], flags=["flexible"], reasons=[], status="new",
        url="https://x/7", description="desc",
    )
    assert "Competition:" not in text


def test_format_brief_omits_recruiter_and_linkedin_lines_when_absent():
    text = format_brief(
        job_id=7, title="React Dev", company="Acme", location="Adelaide SA", work_type="contract",
        salary="$90/h", score=80, rule_score=75, llm_score=88, llm_note="Strong React",
        matched=["React"], missing=["Kotlin"], flags=["flexible"], reasons=[], status="new",
        url="https://x/7", description="desc",
    )
    assert "Recruiter:" not in text
    assert "LinkedIn:" not in text


def test_format_brief():
    text = format_brief(
        job_id=7, title="React Dev", company="Acme", location="Adelaide SA", work_type="contract",
        salary="$90/h", score=80, rule_score=75, llm_score=88, llm_note="Strong React",
        matched=["React"], missing=["Kotlin"], flags=["flexible"], reasons=[], status="new",
        url="https://x/7", description="We need React. " * 500,
    )
    assert text.startswith("#7 React Dev — Acme")
    assert "Matched: React" in text and "Missing: Kotlin" in text
    assert "AI 88" in text
    assert len(text) < 5000
    assert _no_disallowed_chars(text)


def test_notifier_send_file_stages_into_openclaw_media_dir(monkeypatch, tmp_path):
    calls = []
    seen = {}

    def fake_run(cmd, **kw):
        calls.append(cmd)
        staged = Path(cmd[cmd.index("--media") + 1])
        seen["exists_during_send"] = staged.exists()
        seen["content"] = staged.read_bytes()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    media = tmp_path / "openclaw-media"
    Notifier("openclaw", "123", media_dir=media).send_file(pdf, "#7 resume")
    cmd = calls[0]
    staged = Path(cmd[cmd.index("--media") + 1])
    assert staged.parent == media and staged.name.endswith("-r.pdf")
    assert cmd[:7] == ["openclaw", "message", "send", "--channel", "telegram", "--target", "123"]
    assert "--force-document" in cmd and cmd[-2:] == ["--message", "#7 resume"]
    assert seen == {"exists_during_send": True, "content": b"%PDF-1.4 test"}
    assert not staged.exists()  # cleaned up after sending


OVERVIEW = [
    {"city": "adelaide", "total": 50, "flexible": 20, "flexible_share": 0.4},
    {"city": "melbourne", "total": 120, "flexible": 70, "flexible_share": 0.583},
    {"city": "sydney", "total": 90, "flexible": 30, "flexible_share": 0.333},
    {"city": "perth", "total": 40, "flexible": 10, "flexible_share": 0.25},
]
TOP_SKILLS = [
    {"skill": "Java", "count": 10, "share": 0.4, "you_have": True},
    {"skill": "C#", "count": 8, "share": 0.32, "you_have": False},
]
TOP_GAPS = [
    {"skill": "Kubernetes", "count": 6, "share": 0.24, "example_titles": ["DevOps Engineer"],
     "role_families": ["devops_cloud"]},
]
H2H = ["Java vs C#: Adelaide 40%/32% - Melbourne 55%/20%"]


def test_format_market_brief_has_no_emoji_and_is_plain_text():
    text = format_market_brief(OVERVIEW, TOP_SKILLS, TOP_GAPS, H2H, "melbourne", 0.583, "https://sh")
    assert all(ord(ch) < 0x2100 or ch in "—·…-" for ch in text)


def test_format_market_brief_includes_city_totals_and_flexible_share():
    text = format_market_brief(OVERVIEW, TOP_SKILLS, TOP_GAPS, H2H, "melbourne", 0.583, "https://sh")
    assert "Adelaide: 50 jobs, 40% flexible" in text
    assert "Melbourne: 120 jobs, 58% flexible" in text


def test_format_market_brief_includes_top_skills_with_have_markers():
    text = format_market_brief(OVERVIEW, TOP_SKILLS, TOP_GAPS, H2H, "melbourne", 0.583, "https://sh")
    assert "Java 40% (have)" in text
    assert "C# 32% (gap)" in text


def test_format_market_brief_includes_gaps_and_head_to_head_and_best_city():
    text = format_market_brief(OVERVIEW, TOP_SKILLS, TOP_GAPS, H2H, "melbourne", 0.583, "https://sh")
    assert "Kubernetes 24%" in text
    assert "Java vs C#: Adelaide 40%/32% - Melbourne 55%/20%" in text
    assert "Best city for flexible roles: Melbourne (58%)" in text
    assert text.rstrip().endswith("sh/insights")


def test_notifier_send_file_failure_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "nope"))
    with pytest.raises(NotifyError):
        pdf = tmp_path / "r.pdf"
        pdf.write_bytes(b"x")
        Notifier("openclaw", "123", media_dir=tmp_path / "m").send_file(pdf, "c")
