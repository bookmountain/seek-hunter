import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import repo
from seekhunter.config import Env
from seekhunter.domain import JobData
from seekhunter.models import Tailoring, utcnow
from seekhunter.notify import NotifyError
from seekhunter.tailor import current
from seekhunter.tailor.engine import TailorError
from seekhunter.tailor.pipeline import run_tailoring, send_tailoring
from tests.pdf_helpers import FakeCompiler

RESUME_TEX = "\\documentclass{article}\n\\newcommand{\\resumeHeader}{B}\n\\begin{document}\n\\end{document}\n"
PARAS = ["I build React apps with TypeScript. " * 12, "At Microsoft I kept Jest coverage high. " * 8,
         "I would enjoy talking with you. " * 6]
REPLY = json.dumps({
    "summary": "Full-stack Software Engineer with 5 years of experience in React and AI.",
    "skills": [{"id": "languages", "items": ["Python", "Kotlin"]}],
    "experiences": [], "projects": ["microservice-demo"], "keywords_matched": ["React"], "gaps": ["Go"],
    "cover_letter": {"greeting": "Dear Brayden,", "paragraphs": PARAS, "sign_off": "Kind regards,"},
})


class FakeNotifier:
    def __init__(self, fail: bool = False):
        self.files: list[tuple[Path, str]] = []
        self.texts: list[str] = []
        self.fail = fail

    def send(self, text: str) -> None:
        self.texts.append(text)

    def send_file(self, path: Path, caption: str) -> None:
        if self.fail:
            raise NotifyError("telegram down")
        assert path.exists()
        self.files.append((path, caption))


@pytest.fixture
def setup(tmp_path, fixtures_dir):
    latex = tmp_path / "latex"
    shutil.copytree(fixtures_dir / "resume", latex / "sections" / "resume")
    (latex / "resume.tex").write_text(RESUME_TEX)
    env = Env(data_dir=tmp_path / "data", latex_dir=latex, resume_dir=latex / "sections" / "resume")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    job, _ = repo.upsert_job(session, JobData(
        source="seek", external_id="1", title="React Developer", company="Acme & Co", location="Adelaide SA",
        work_type="contract", url="u", description_html="<p>We need React and Go.</p>"))
    repo.set_contacts(session, job, name="Brayden Smith")
    yield env, session, job
    session.close()


def _run(setup, *, llm=lambda p: REPLY, compiler=None, notifier=None, send=False):
    env, session, job = setup
    t = repo.create_tailoring(session, job.id, send=send)
    return run_tailoring(session, t.id, env=env, llm=llm,
                         compiler=compiler or FakeCompiler({"resume.tex": 2}),
                         notifier=notifier or FakeNotifier(), today=date(2026, 10, 17))


def test_successful_tailoring(setup):
    env, session, job = setup
    t = _run(setup)
    assert t.status == "done" and t.error is None and t.finished_at is not None
    assert t.provider == "openclaw"
    out = Path(t.out_dir)
    assert out == env.data_dir / "tailored" / str(t.id)
    for name in ("resume.pdf", "cover_letter.pdf", "resume-1.png", "resume-2.png", "cover_letter-1.png"):
        assert (out / name).exists()
    assert t.result["pages"] == {"resume": 2, "cover_letter": 1}
    assert t.result["tailored"]["skills"][0]["items"] == ["Python"]
    assert t.result["base"]["skills"][0]["items"] == ["TypeScript", "Python", "C#", "Java"]
    assert t.result["keywords_matched"] == ["React"] and t.result["gaps"] == ["Go"]
    assert t.result["cover_letter"]["greeting"] == "Dear Brayden,"
    assert any("Kotlin" in w for w in t.warnings)
    assert current.read_current(env.data_dir, t.resume_hash)["pages"] == 2  # base preview cached too
    assert t.sent_at is None


def test_llm_failure_marks_failed_and_tells_telegram_when_send_requested(setup):
    notifier = FakeNotifier()

    def boom(prompt):
        raise TailorError("openclaw exit 1: boom")

    t = _run(setup, llm=boom, notifier=notifier, send=True)
    assert t.status == "failed" and "boom" in t.error
    assert notifier.files == [] and "failed" in notifier.texts[0]


def test_compile_failure_keeps_log(setup):
    t = _run(setup, compiler=FakeCompiler(fail="tectonic exit 1:\n! Undefined control sequence."))
    assert t.status == "failed" and "Undefined control sequence" in t.error


def test_send_requested_delivers_both_pdfs(setup):
    notifier = FakeNotifier()
    t = _run(setup, notifier=notifier, send=True)
    assert t.status == "done" and t.sent_at is not None
    names = [p.name for p, _ in notifier.files]
    assert names == ["Book_Sam_Resume_Acme_Co.pdf", "Book_Sam_Cover_Letter_Acme_Co.pdf"]
    assert notifier.files[0][1].startswith(f"#{t.job_id} Tailored resume")


def test_send_failure_is_a_warning_not_a_failure(setup):
    t = _run(setup, notifier=FakeNotifier(fail=True), send=True)
    assert t.status == "done" and t.sent_at is None
    assert any("Telegram" in w for w in t.warnings)


def test_send_tailoring_requires_done(setup):
    env, session, job = setup
    t = repo.create_tailoring(session, job.id)
    with pytest.raises(ValueError):
        send_tailoring(session, t, job, FakeNotifier())


def test_active_tailoring_expires_stale(setup):
    _, session, job = setup
    old = repo.create_tailoring(session, job.id)
    old.created_at = utcnow() - timedelta(hours=2)
    repo.save_tailoring(session, old)
    assert repo.active_tailoring(session, job.id, utcnow()) is None
    assert session.get(Tailoring, old.id).status == "failed"
    fresh = repo.create_tailoring(session, job.id)
    assert repo.active_tailoring(session, job.id, utcnow()).id == fresh.id
    assert [t.id for t in repo.list_tailorings(session, job.id)] == [fresh.id, old.id]


def test_tailoring_records_headline_and_target_phrases(setup):
    t = _run(setup)
    # deterministic fallback (the reply has none): no fixture title is a "Developer", no ad skill is listed
    assert t.result["tailored"]["headline"] == "Software Engineer"
    assert t.result["base"]["headline"] is None
    assert t.result["target_phrases"]["source"] == "seekhunter"
    assert "React" in t.result["target_phrases"]["supported"]
    assert "Go" in t.result["target_phrases"]["unsupported"]


def test_retailor_reuses_resume_matcher_keywords(setup):
    env, session, job = setup
    old = repo.create_tailoring(session, job.id)
    old.status, old.result = "done", {"resume_matcher": {"status": "done", "job_keywords": {
        "required_skills": ["React", "Hibernate"], "preferred_skills": [], "keywords": ["Agile development"]},
        "missing_keywords": ["JIRA"], "matched_keywords": []}}
    repo.save_tailoring(session, old)
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        return REPLY

    t = _run(setup, llm=llm)
    assert t.result["target_phrases"]["source"] == "resume_matcher"
    assert t.result["target_phrases"]["unsupported"] == ["Hibernate", "Agile development", "JIRA"]
    assert "Hibernate" in prompts[0]

    t2 = repo.create_tailoring(session, job.id)
    t2 = run_tailoring(session, t2.id, env=env, llm=llm, compiler=FakeCompiler({"resume.tex": 2}),
                       today=date(2026, 10, 17), reuse_rm_keywords=False)
    assert t2.result["target_phrases"]["source"] == "seekhunter"


def test_headline_dropped_from_result_when_it_adds_a_page(setup):
    def compiler(work_dir, tex_name):
        from tests.pdf_helpers import write_pdf

        pdf = work_dir / tex_name.replace(".tex", ".pdf")
        write_pdf(pdf, 3 if "resumeHeadline" in (work_dir / tex_name).read_text() else 2)
        return pdf

    t = _run(setup, compiler=compiler)
    assert t.status == "done"
    assert t.result["tailored"]["headline"] is None
    assert any("headline" in w.lower() for w in t.warnings)
