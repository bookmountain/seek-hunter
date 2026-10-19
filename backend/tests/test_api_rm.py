"""API surface for ATS scores and the Resume-Matcher integration."""

from datetime import timedelta

from seekhunter import api as api_module
from seekhunter import repo
from seekhunter.models import Tailoring, utcnow
from seekhunter.resume_matcher import RMError
from tests.test_api_tailor import AUTH, _finished, ctx  # noqa: F401  (fixture)

ATS_T = {"score": 81.0, "breakdown": {"keyword_match": 80.0, "skills_coverage": 75.0, "title_alignment": 75.0,
                                      "section_completeness": 100.0, "date_consistency": 90.0},
         "missing_keywords": ["Go"], "matched_keywords": ["React"]}
RM = {"status": "done", "started_at": "2026-10-18T01:00:00", "finished_at": "2026-10-18T01:03:00",
      "error": None, "warnings": [], "rm_master_id": "m1", "rm_job_id": "j1", "rm_resume_id": "t1",
      "ats_score": 66.5, "sub_scores": {"keyword_match": 50.0, "title_match": None},
      "missing_keywords": ["Go"], "matched_keywords": ["React"], "injectable_keywords": [],
      "recommendations": ["Add Go"], "job_keywords": {"required_skills": ["React", "Go"]},
      "interview_prep": {"resume_questions": [{"question": "Q?", "suggested_answer_points": ["a"]}]},
      "outreach_message": "Hi Brayden"}


def _with_result(c, **extra) -> int:
    tid = _finished(c)
    with c.session() as s:
        t = s.get(Tailoring, tid)
        t.result = {**t.result, **extra}
        repo.save_tailoring(s, t)
    return tid


def test_detail_includes_stored_ats_and_resume_matcher(ctx):  # noqa: F811
    tid = _with_result(ctx, ats={"keywords_source": "resume_matcher", "current": {**ATS_T, "score": 62.0},
                                 "tailored": ATS_T}, resume_matcher=RM)
    d = ctx.client.get(f"/api/tailorings/{tid}").json()
    assert d["ats"]["current"]["score"] == 62.0 and d["ats"]["tailored"]["score"] == 81.0
    assert d["ats"]["keywords_source"] == "resume_matcher"
    assert set(d["ats"]["tailored"]["breakdown"]) == {"keyword_match", "skills_coverage", "title_alignment",
                                                      "section_completeness", "date_consistency"}
    r = d["resume_matcher"]
    assert r["status"] == "done" and r["ats_score"] == 66.5 and r["outreach_message"] == "Hi Brayden"
    assert r["interview_prep"]["resume_questions"][0]["question"] == "Q?"
    assert r["missing_keywords"] == ["Go"] and r["matched_keywords"] == ["React"]
    assert r["rm_resume_id"] == "t1" and r["error"] is None


def test_detail_computes_ats_for_older_tailorings(ctx):  # noqa: F811
    tid = _finished(ctx)  # stored before result["ats"] existed
    d = ctx.client.get(f"/api/tailorings/{tid}").json()
    assert d["ats"]["keywords_source"] == "seekhunter"
    assert 0 <= d["ats"]["current"]["score"] <= 100 and 0 <= d["ats"]["tailored"]["score"] <= 100
    assert d["ats"]["current"]["missing_keywords"] == ["Go"]
    assert d["ats"]["tailored"]["missing_keywords"] == ["React", "Go"]  # fixture's summary drops React
    assert d["resume_matcher"] is None


def test_detail_running_has_null_ats(ctx):  # noqa: F811
    with ctx.session() as s:
        t = repo.create_tailoring(s, ctx.job_id)
        tid = t.id
    d = ctx.client.get(f"/api/tailorings/{tid}").json()
    assert d["ats"] == {"current": None, "tailored": None, "keywords_source": None}
    assert d["resume_matcher"] is None


def test_stale_running_rm_reported_failed(ctx):  # noqa: F811
    old = (utcnow() - timedelta(hours=2)).isoformat()
    tid = _with_result(ctx, resume_matcher={"status": "running", "started_at": old, "error": None})
    r = ctx.client.get(f"/api/tailorings/{tid}").json()["resume_matcher"]
    assert r["status"] == "failed" and "timed out" in r["error"]


def test_list_has_ats_numbers(ctx):  # noqa: F811
    tid = _with_result(ctx, ats={"keywords_source": "seekhunter", "current": {**ATS_T, "score": 62.0},
                                 "tailored": ATS_T})
    row = next(r for r in ctx.client.get("/api/tailorings").json() if r["id"] == tid)
    assert row["ats_current"] == 62.0 and row["ats_tailored"] == 81.0


def test_rerun_requires_token_done_and_config(ctx, monkeypatch):  # noqa: F811
    tid = _finished(ctx)
    url = f"/api/tailorings/{tid}/resume-matcher"
    assert ctx.client.post(url).status_code == 401
    monkeypatch.setenv("RM_BASE_URL", "")
    api_module.get_env.cache_clear()
    r = ctx.client.post(url, headers=AUTH)
    assert r.status_code == 409 and "RM_BASE_URL" in r.json()["detail"]
    with ctx.session() as s:
        t = repo.create_tailoring(s, ctx.job_id)
        running_id = t.id
    monkeypatch.setenv("RM_BASE_URL", "http://rm.test")
    api_module.get_env.cache_clear()
    assert ctx.client.post(f"/api/tailorings/{running_id}/resume-matcher", headers=AUTH).status_code == 409


def test_rerun_marks_queued_and_spawns(ctx, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RM_BASE_URL", "http://rm.test")
    api_module.get_env.cache_clear()
    tid = _with_result(ctx, resume_matcher={**RM, "status": "failed", "error": "boom"})
    r = ctx.client.post(f"/api/tailorings/{tid}/resume-matcher", headers=AUTH)
    assert r.status_code == 202 and r.json() == {"status": "queued", "started": True}
    assert ctx.spawned[-1][1:] == ["-m", "seekhunter.cli", "resume-matcher", str(tid)]
    d = ctx.client.get(f"/api/tailorings/{tid}").json()
    assert d["resume_matcher"]["status"] == "queued" and d["resume_matcher"]["error"] is None
    # A second click while it's queued/running doesn't spawn again.
    r = ctx.client.post(f"/api/tailorings/{tid}/resume-matcher", headers=AUTH)
    assert r.json() == {"status": "queued", "started": False} and len(ctx.spawned) == 1


class _StatusRM:
    def __init__(self, payload=None, error=None):
        self.payload, self.error = payload, error
        self.base_url = "http://rm.test"

    def status(self):
        if self.error:
            raise self.error
        return self.payload


def test_rm_status_disabled(ctx, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RM_BASE_URL", "")
    api_module.get_env.cache_clear()
    s = ctx.client.get("/api/resume-matcher/status").json()
    assert s["enabled"] is False and s["ready"] is False and s["reachable"] is False


def test_rm_status_needs_sign_in(ctx, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api_module, "client_from_env", lambda env: _StatusRM({
        "status": "setup_required", "llm_configured": False, "llm_healthy": False, "agent_mode": False,
        "has_master_resume": False, "database_stats": {}}))
    s = ctx.client.get("/api/resume-matcher/status").json()
    assert s["enabled"] and s["reachable"] and s["llm_configured"] is False and s["ready"] is False
    assert s["status"] == "setup_required" and s["settings_url"] == "http://rm.test/settings"


def test_rm_status_ready(ctx, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api_module, "client_from_env", lambda env: _StatusRM({
        "status": "setup_required", "llm_configured": True, "llm_healthy": True, "agent_mode": False,
        "has_master_resume": False, "database_stats": {}}))
    s = ctx.client.get("/api/resume-matcher/status").json()
    assert s["ready"] is True  # SeekHunter uploads the master itself


def test_rm_status_unreachable(ctx, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api_module, "client_from_env",
                        lambda env: _StatusRM(error=RMError("Resume-Matcher unreachable: refused")))
    s = ctx.client.get("/api/resume-matcher/status").json()
    assert s["enabled"] and s["reachable"] is False and "refused" in s["error"]


def test_regenerate_cover_letter_marks_queued_spawns_and_versions_urls(ctx):  # noqa: F811
    tid = _finished(ctx)
    assert ctx.client.post(f"/api/tailorings/{tid}/cover-letter").status_code == 401
    r = ctx.client.post(f"/api/tailorings/{tid}/cover-letter", headers=AUTH)
    assert r.status_code == 202 and r.json() == {"status": "queued", "started": True}
    assert ctx.spawned[-1][1:] == ["-m", "seekhunter.cli", "cover-letter", str(tid)]
    d = ctx.client.get(f"/api/tailorings/{tid}").json()
    assert d["cover_letter_regen"]["status"] == "queued"
    again = ctx.client.post(f"/api/tailorings/{tid}/cover-letter", headers=AUTH)
    assert again.json() == {"status": "queued", "started": False} and len(ctx.spawned) == 1
    with ctx.session() as s:
        t = s.get(Tailoring, tid)
        t.result = {**t.result, "cover_letter_regen": {"status": "done", "version": 2}}
        repo.save_tailoring(s, t)
    files = ctx.client.get(f"/api/tailorings/{tid}").json()["files"]
    assert files["cover_letter_pdf"].endswith("cover_letter.pdf?v=2")
    assert files["cover_letter_pages"][0].endswith("1.png?v=2") and "?v" not in files["resume_pdf"]


def test_regenerate_cover_letter_requires_finished(ctx):  # noqa: F811
    with ctx.session() as s:
        running_id = repo.create_tailoring(s, ctx.job_id).id
    assert ctx.client.post(f"/api/tailorings/{running_id}/cover-letter", headers=AUTH).status_code == 409


def test_stale_cover_letter_regen_reads_as_failed(ctx):  # noqa: F811
    old = (utcnow() - timedelta(hours=1)).isoformat()
    tid = _with_result(ctx, cover_letter_regen={"status": "running", "started_at": old})
    regen = ctx.client.get(f"/api/tailorings/{tid}").json()["cover_letter_regen"]
    assert regen["status"] == "failed" and "timed out" in regen["error"]
