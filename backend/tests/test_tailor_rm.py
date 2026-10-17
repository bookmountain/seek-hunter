"""SeekHunter's own ATS score on every tailoring, and the best-effort Resume-Matcher step."""

from datetime import date

import pytest
from sqlmodel import select

from seekhunter import repo
from seekhunter.models import Tailoring
from seekhunter.resume_matcher import RMError
from seekhunter.tailor import rm
from seekhunter.tailor.pipeline import run_tailoring
from tests.pdf_helpers import FakeCompiler
from tests.test_tailor_pipeline import REPLY, FakeNotifier, setup  # noqa: F401  (fixture)

PREP = {"role_fit_analysis": ["Strong React fit"], "resume_questions": [
    {"question": "Tell me about Jest at Microsoft?", "focus_area": "Testing",
     "suggested_answer_points": ["Coverage", "RTL"]}],
    "project_follow_ups": [], "talking_points": [],
    "skill_gaps": [{"skill": "Go", "why_it_matters": "Backend", "preparation_suggestion": "Build a demo"}]}
JOB_KEYWORDS = {"role": "React Developer", "company": "Acme", "required_skills": ["React", "Go"],
                "preferred_skills": ["Kubernetes"], "keywords": ["TypeScript"]}


class FakeRM:
    def __init__(self, *, llm=True, parse="ready", fail: str | None = None, prep_inline=False,
                 prep_fails=False, keywords=JOB_KEYWORDS):
        self.llm, self.parse, self.fail = llm, parse, fail
        self.prep_inline, self.prep_fails = prep_inline, prep_fails
        self.keywords = keywords
        self.calls: list[tuple] = []
        self.masters: list[str] = []
        self.n = 0

    def _maybe_fail(self, name):
        if self.fail == name:
            raise RMError(f"{name} exploded", status=500)

    def status(self):
        self.calls.append(("status",))
        self._maybe_fail("status")
        return {"status": "ready", "llm_configured": self.llm, "llm_healthy": self.llm, "agent_mode": False,
                "has_master_resume": bool(self.masters), "database_stats": {}}

    def upload_resume(self, pdf, filename="resume.pdf"):
        assert pdf.exists() and pdf.name == "resume.pdf"
        self.n += 1
        rid = f"m{self.n}"
        self.calls.append(("upload_resume", filename))
        self.masters.append(rid)
        return {"message": "ok", "request_id": "r", "resume_id": rid, "processing_status": self.parse,
                "is_master": True, "is_default_master": False}

    def set_default(self, rid):
        self.calls.append(("set_default", rid))
        return {"resume_id": rid, "is_default_master": True}

    def delete_resume(self, rid):
        self.calls.append(("delete_resume", rid))
        self.masters.remove(rid)
        return {"message": "Resume deleted successfully"}

    def list_resumes(self, include_master=True):
        self.calls.append(("list_resumes",))
        return [{"resume_id": m, "is_master": True} for m in self.masters]

    def upload_job(self, text, resume_id=None):
        self.calls.append(("upload_job", resume_id))
        assert "React Developer" in text and "We need React and Go." in text
        return "j1"

    def improve(self, resume_id, job_id):
        self.calls.append(("improve", resume_id, job_id))
        self._maybe_fail("improve")
        return {"request_id": "q", "resume_id": "t1", "job_id": job_id,
                "resume_preview": {"summary": "React and TypeScript engineer", "workExperience": [],
                                   "additional": {"technicalSkills": ["React", "TypeScript"]}},
                "outreach_message": None, "interview_prep": PREP if self.prep_inline else None,
                "ats_score": {"overall_score": 64.0, "sub_scores": {"keyword_match": 50.0},
                              "missing_keywords": ["Go"], "injectable_keywords": [],
                              "recommendations": ["Add Go"]},
                "warnings": []}

    def ats_score(self, tid):
        self.calls.append(("ats_score", tid))
        return {"score": {"overall_score": 66.5, "sub_scores": {
            "keyword_match": 50.0, "skills_coverage": 66.7, "title_match": 75.0,
            "section_completeness": 100.0, "date_consistency": None},
            "missing_keywords": ["Go", "Kubernetes"], "injectable_keywords": [],
            "recommendations": ["Add these high-priority missing keywords: Go."]}, "calculated_at": "x"}

    def get_job(self, job_id):
        self.calls.append(("get_job", job_id))
        return {"job_id": job_id, "content": "...", "job_keywords": self.keywords}

    def interview_prep(self, tid):
        self.calls.append(("interview_prep", tid))
        if self.prep_fails:
            raise RMError("prep exploded", status=500)
        return PREP

    def outreach(self, tid):
        self.calls.append(("outreach", tid))
        return "Hi Brayden, I'd love to connect about the React role."

    def names(self):
        return [c[0] for c in self.calls]


def _run(setup, client=None, **kw):  # noqa: F811
    env, session, job = setup
    t = repo.create_tailoring(session, job.id)
    return run_tailoring(session, t.id, env=env, llm=lambda p: REPLY,
                         compiler=FakeCompiler({"resume.tex": 2}), notifier=FakeNotifier(),
                         today=date(2026, 10, 17), resume_matcher=client, **kw)


def test_ats_scores_current_and_tailored_with_seekhunter_keywords(setup):  # noqa: F811
    t = _run(setup)
    ats = t.result["ats"]
    assert ats["keywords_source"] == "seekhunter"
    for side in ("current", "tailored"):
        assert set(ats[side]["breakdown"]) == {"keyword_match", "skills_coverage", "title_alignment",
                                               "section_completeness", "date_consistency"}
        assert 0 <= ats[side]["score"] <= 100
    assert "Go" in ats["tailored"]["missing_keywords"]  # REPLY's gap
    assert "resume_matcher" not in t.result  # RM disabled


def test_rm_step_stores_everything(setup):  # noqa: F811
    env, session, _ = setup
    fake = FakeRM()
    t = _run(setup, fake)
    assert t.status == "done"
    r = t.result["resume_matcher"]
    assert r["status"] == "done" and r["error"] is None
    assert (r["rm_master_id"], r["rm_job_id"], r["rm_resume_id"]) == ("m1", "j1", "t1")
    assert r["ats_score"] == 66.5
    assert r["sub_scores"]["title_match"] == 75.0
    assert r["missing_keywords"] == ["Go", "Kubernetes"]
    assert r["matched_keywords"] == ["React", "TypeScript"]
    assert r["recommendations"] == ["Add these high-priority missing keywords: Go."]
    assert r["interview_prep"]["resume_questions"][0]["question"] == "Tell me about Jest at Microsoft?"
    assert r["outreach_message"].startswith("Hi Brayden")
    assert r["job_keywords"] == JOB_KEYWORDS
    assert ("set_default", "m1") in fake.calls and ("improve", "m1", "j1") in fake.calls
    # SeekHunter's own resumes are re-scored against RM's keyword list.
    assert t.result["ats"]["keywords_source"] == "resume_matcher"
    assert "Kubernetes" in t.result["ats"]["tailored"]["missing_keywords"]
    assert t.progress == "Done"
    assert session.exec(select(rm.ResumeMatcherMaster)).one().rm_resume_id == "m1"


def test_master_synced_only_when_resume_hash_changes(setup):  # noqa: F811
    env, session, _ = setup
    fake = FakeRM()
    _run(setup, fake)
    _run(setup, fake)
    assert fake.names().count("upload_resume") == 1
    # Edit the resume -> new hash -> new master uploaded and set default; the old one is removed.
    summary = env.resume_dir / "summary.tex"
    summary.write_text(summary.read_text() + "\nAlso Go.\n")
    t3 = _run(setup, fake)
    assert fake.names().count("upload_resume") == 2
    assert ("set_default", "m2") in fake.calls and ("delete_resume", "m1") in fake.calls
    rows = session.exec(select(rm.ResumeMatcherMaster)).all()
    assert [(r.resume_hash, r.rm_resume_id) for r in rows] == [(t3.resume_hash, "m2")]


def test_master_reuploaded_if_rm_lost_it(setup):  # noqa: F811
    fake = FakeRM()
    _run(setup, fake)
    fake.masters.clear()  # RM database reset
    t = _run(setup, fake)
    assert fake.names().count("upload_resume") == 2
    assert t.result["resume_matcher"]["rm_master_id"] == "m2"


def test_rm_failure_never_fails_the_tailoring(setup):  # noqa: F811
    t = _run(setup, FakeRM(fail="improve"))
    assert t.status == "done" and t.error is None
    r = t.result["resume_matcher"]
    assert r["status"] == "failed" and "improve exploded" in r["error"]
    assert t.result["ats"]["keywords_source"] == "seekhunter"  # own score still there
    assert t.result["tailored"]  # tailoring result intact


def test_unexpected_exception_is_contained(setup):  # noqa: F811
    class Broken(FakeRM):
        def status(self):
            raise RuntimeError("kaboom")

    t = _run(setup, Broken())
    assert t.status == "done" and t.result["resume_matcher"]["status"] == "failed"
    assert "kaboom" in t.result["resume_matcher"]["error"]


def test_rm_without_llm_is_unavailable(setup):  # noqa: F811
    fake = FakeRM(llm=False)
    t = _run(setup, fake)
    r = t.result["resume_matcher"]
    assert r["status"] == "unavailable" and "sign in" in r["error"].lower()
    assert "upload_resume" not in fake.names()


def test_unparsed_master_is_not_remembered(setup):  # noqa: F811
    env, session, _ = setup
    fake = FakeRM(parse="failed")
    t = _run(setup, fake)
    assert t.result["resume_matcher"]["status"] == "failed"
    assert ("delete_resume", "m1") in fake.calls
    assert session.exec(select(rm.ResumeMatcherMaster)).all() == []


def test_interview_prep_failure_is_a_warning(setup):  # noqa: F811
    t = _run(setup, FakeRM(prep_fails=True))
    r = t.result["resume_matcher"]
    assert r["status"] == "done" and r["interview_prep"] is None
    assert any("interview prep" in w.lower() for w in r["warnings"])


def test_inline_interview_prep_skips_extra_call(setup):  # noqa: F811
    fake = FakeRM(prep_inline=True)
    _run(setup, fake)
    assert "interview_prep" not in fake.names()


def test_deferred_marks_queued_then_step_runs(setup):  # noqa: F811
    env, session, _ = setup
    fake = FakeRM()
    t = _run(setup, fake, defer_resume_matcher=True)
    assert t.result["resume_matcher"]["status"] == "queued" and fake.calls == []
    t = rm.run_resume_matcher(session, t.id, env=env, client=fake)
    assert t.result["resume_matcher"]["status"] == "done"


def test_step_requires_finished_tailoring(setup):  # noqa: F811
    env, session, job = setup
    t = repo.create_tailoring(session, job.id)
    with pytest.raises(ValueError):
        rm.run_resume_matcher(session, t.id, env=env, client=FakeRM())
    assert session.get(Tailoring, t.id).status == "queued"
