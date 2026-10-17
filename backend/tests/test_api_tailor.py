import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import api as api_module
from seekhunter import repo
from seekhunter.api import create_app
from seekhunter.config import get_env
from seekhunter.db import get_session
from seekhunter.domain import JobData
from seekhunter.models import Tailoring, utcnow
from seekhunter.resume_doc import load_resume_doc
from seekhunter.tailor import current, render
from tests.pdf_helpers import write_pdf, write_png

AUTH = {"Authorization": "Bearer t0k"}
FIXTURES = Path(__file__).parent / "fixtures"
RESUME_TEX = "\\documentclass{article}\n\\begin{document}\n\\end{document}\n"


class Ctx:
    def __init__(self, client, engine, data_dir, latex_dir, job_id, spawned):
        self.client, self.engine, self.data_dir, self.latex_dir = client, engine, data_dir, latex_dir
        self.job_id, self.spawned = job_id, spawned

    def session(self) -> Session:
        return Session(self.engine)


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    latex = tmp_path / "latex"
    shutil.copytree(FIXTURES / "resume", latex / "sections" / "resume")
    (latex / "resume.tex").write_text(RESUME_TEX)
    data = tmp_path / "data"
    monkeypatch.setenv("API_WRITE_TOKEN", "t0k")
    monkeypatch.setenv("ALLOWED_CIDRS", "127.0.0.1/32,testclient/32")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("LATEX_DIR", str(latex))
    monkeypatch.setenv("RESUME_DIR", str(latex / "sections" / "resume"))
    get_env.cache_clear()
    spawned: list[list[str]] = []
    monkeypatch.setattr(api_module.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        job, _ = repo.upsert_job(s, JobData(source="seek", external_id="1", title="React Dev",
                                            company="Acme & Co", location="Adelaide SA", work_type="contract",
                                            url="u", description_html="<p>React</p>"))
        repo.set_contacts(s, job, name="Brayden Smith")
        job_id = job.id

    def override():
        with Session(engine) as s:
            yield s

    app = create_app(init=False)
    app.dependency_overrides[get_session] = override
    yield Ctx(TestClient(app), engine, data, latex, job_id, spawned)
    get_env.cache_clear()


def _finished(c: Ctx, **over) -> int:
    base = load_resume_doc(c.latex_dir / "sections" / "resume")
    tailored = base.model_copy(deep=True)
    tailored.summary = "Tailored summary."
    tailored.skills[0].items = ["Python", "TypeScript"]
    tailored.experiences[0].bullets[0].text = "Reworded bullet with Jest."
    with c.session() as s:
        t = repo.create_tailoring(s, c.job_id)
        out = c.data_dir / "tailored" / str(t.id)
        out.mkdir(parents=True)
        write_pdf(out / "resume.pdf", 2)
        write_pdf(out / "cover_letter.pdf")
        for name in ("resume-1.png", "resume-2.png", "cover_letter-1.png"):
            write_png(out / name)
        t.status, t.progress, t.finished_at, t.provider = "done", "Done", utcnow(), "openclaw"
        t.out_dir, t.resume_hash = str(out), "abcdef0123456789"
        t.warnings = ["Skills · Languages: dropped 'Kotlin' (not in your resume)."]
        t.result = {
            "base": base.model_dump(), "tailored": tailored.model_dump(),
            "keywords_matched": ["React"], "gaps": ["Go"],
            "cover_letter": {"greeting": "Dear Brayden,", "paragraphs": ["One two.", "Three."],
                             "sign_off": "Kind regards,"},
            "pages": {"resume": 2, "cover_letter": 1},
        }
        for k, v in over.items():
            setattr(t, k, v)
        repo.save_tailoring(s, t)
        return t.id


def test_start_tailoring_requires_token_and_spawns_cli(ctx):
    assert ctx.client.post(f"/api/jobs/{ctx.job_id}/tailor").status_code == 401
    r = ctx.client.post(f"/api/jobs/{ctx.job_id}/tailor?send=1", headers=AUTH)
    assert r.status_code == 202
    tid = r.json()["tailoring_id"]
    assert r.json() == {"tailoring_id": tid, "status": "queued", "reused": False}
    cmd = ctx.spawned[0]
    assert cmd[1:] == ["-m", "seekhunter.cli", "tailor", str(ctx.job_id), "--tailoring-id", str(tid),
                       "--send"]
    with ctx.session() as s:
        assert s.get(Tailoring, tid).send_requested is True


def test_start_tailoring_reuses_active_and_upgrades_send(ctx):
    first = ctx.client.post(f"/api/jobs/{ctx.job_id}/tailor", headers=AUTH).json()
    assert ctx.spawned[0][-1] == str(first["tailoring_id"])  # no --send
    again = ctx.client.post(f"/api/jobs/{ctx.job_id}/tailor?send=1", headers=AUTH).json()
    assert again == {"tailoring_id": first["tailoring_id"], "status": "queued", "reused": True}
    assert len(ctx.spawned) == 1
    with ctx.session() as s:
        assert s.get(Tailoring, first["tailoring_id"]).send_requested is True


def test_start_tailoring_unknown_job_404(ctx):
    assert ctx.client.post("/api/jobs/999/tailor", headers=AUTH).status_code == 404


def test_list_tailorings(ctx):
    tid = _finished(ctx)
    rows = ctx.client.get(f"/api/jobs/{ctx.job_id}/tailorings").json()
    assert [r["id"] for r in rows] == [tid]
    row = rows[0]
    assert row["status"] == "done" and row["pages"] == {"resume": 2, "cover_letter": 1}
    assert row["warnings_count"] == 1 and row["resume_hash"] == "abcdef0123456789"
    assert set(row) == {"id", "job_id", "status", "progress", "created_at", "started_at", "finished_at",
                        "provider", "error", "send_requested", "sent_at", "resume_hash", "pages",
                        "warnings_count"}
    assert ctx.client.get("/api/jobs/999/tailorings").status_code == 404


def test_tailoring_detail_with_changes_and_urls(ctx):
    tid = _finished(ctx)
    d = ctx.client.get(f"/api/tailorings/{tid}").json()
    assert d["status"] == "done"
    assert d["keywords_matched"] == ["React"] and d["gaps"] == ["Go"]
    assert d["warnings"][0].startswith("Skills")
    assert d["cover_letter"]["text"] == "Dear Brayden,\n\nOne two.\n\nThree.\n\nKind regards,\nBook Sam"
    assert d["cover_letter"]["word_count"] == 3
    assert d["job"] == {"id": ctx.job_id, "title": "React Dev", "company": "Acme & Co",
                        "location": "Adelaide SA", "work_type": "contract", "contact_name": "Brayden Smith"}
    changes = d["changes"]
    assert changes[0] == {
        "type": "summary",
        "before": "Full-stack Software Engineer with 5 years of experience in **React** and AI.",
        "after": "Tailored summary.", "changed": True}
    bullet = next(c for c in changes if c["type"] == "bullet")
    assert bullet["status"] == "reworded" and bullet["experience"] == "microsoft"
    skills = next(c for c in changes if c["type"] == "skills")
    assert skills["before"] == ["TypeScript", "Python", "C#", "Java"]
    assert skills["after"] == ["Python", "TypeScript"]
    assert changes[-1] == {"type": "projects", "included": ["Microservice Demo"], "excluded": []}
    assert d["files"] == {
        "resume_pdf": f"/api/tailorings/{tid}/resume.pdf",
        "cover_letter_pdf": f"/api/tailorings/{tid}/cover_letter.pdf",
        "resume_pages": [f"/api/tailorings/{tid}/pages/resume/1.png",
                         f"/api/tailorings/{tid}/pages/resume/2.png"],
        "cover_letter_pages": [f"/api/tailorings/{tid}/pages/cover_letter/1.png"],
    }
    assert d["current"] == {"hash": "abcdef0123456789", "ready": False, "pages": 0, "pdf_url": None,
                            "page_urls": [], "error": None}


def test_tailoring_detail_running_has_no_files(ctx):
    with ctx.session() as s:
        t = repo.create_tailoring(s, ctx.job_id)
        t.status, t.progress = "running", "Tailoring with AI"
        repo.save_tailoring(s, t)
        tid = t.id
    d = ctx.client.get(f"/api/tailorings/{tid}").json()
    assert d["progress"] == "Tailoring with AI"
    assert d["files"] is None and d["changes"] == [] and d["cover_letter"] is None and d["current"] is None
    assert ctx.client.get(f"/api/tailorings/{tid}/resume.pdf").status_code == 404
    assert ctx.client.get("/api/tailorings/999").status_code == 404


def test_tailoring_files(ctx):
    tid = _finished(ctx)
    r = ctx.client.get(f"/api/tailorings/{tid}/resume.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert 'inline; filename="Book_Sam_Resume_Acme_Co.pdf"' in r.headers["content-disposition"]
    r = ctx.client.get(f"/api/tailorings/{tid}/cover_letter.pdf")
    assert "Book_Sam_Cover_Letter_Acme_Co.pdf" in r.headers["content-disposition"]
    r = ctx.client.get(f"/api/tailorings/{tid}/pages/resume/2.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert ctx.client.get(f"/api/tailorings/{tid}/pages/resume/3.png").status_code == 404
    assert ctx.client.get(f"/api/tailorings/{tid}/pages/secrets/1.png").status_code == 404
    assert ctx.client.get(f"/api/tailorings/{tid}/other.pdf").status_code == 404


def test_file_routes_are_ip_gated(ctx, monkeypatch):
    tid = _finished(ctx)
    monkeypatch.setenv("ALLOWED_CIDRS", "10.9.9.9/32")
    get_env.cache_clear()
    assert ctx.client.get(f"/api/tailorings/{tid}/resume.pdf").status_code == 403
    assert ctx.client.get("/api/resume/current.pdf").status_code == 403


def test_send_tailoring(ctx, monkeypatch):
    tid = _finished(ctx)
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    assert ctx.client.post(f"/api/tailorings/{tid}/send").status_code == 401
    r = ctx.client.post(f"/api/tailorings/{tid}/send", headers=AUTH)
    assert r.status_code == 200 and r.json()["sent"] is True and r.json()["sent_at"]
    assert [c[c.index("--media") + 1].rsplit("/", 1)[-1] for c in calls] == [
        "Book_Sam_Resume_Acme_Co.pdf", "Book_Sam_Cover_Letter_Acme_Co.pdf"]
    assert all("--force-document" in c for c in calls)


def test_send_tailoring_errors(ctx, monkeypatch):
    with ctx.session() as s:
        running = repo.create_tailoring(s, ctx.job_id).id
    assert ctx.client.post(f"/api/tailorings/{running}/send", headers=AUTH).status_code == 409
    tid = _finished(ctx)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "down"))
    assert ctx.client.post(f"/api/tailorings/{tid}/send", headers=AUTH).status_code == 502


def test_current_resume_not_built_spawns_preview_once(ctx):
    r = ctx.client.get("/api/resume/current").json()
    h = render.latex_hash(ctx.latex_dir)
    assert r == {"hash": h, "ready": False, "pages": 0, "pdf_url": None, "page_urls": [], "error": None}
    ctx.client.get("/api/resume/current")
    assert ctx.spawned == [[ctx.spawned[0][0], "-m", "seekhunter.cli", "resume-preview"]]
    assert ctx.client.get("/api/resume/current.pdf").status_code == 404


def test_current_resume_ready(ctx):
    from tests.pdf_helpers import FakeCompiler

    info = current.ensure_current(ctx.latex_dir, ctx.data_dir, FakeCompiler({"resume.tex": 2}))
    h = info["hash"]
    r = ctx.client.get("/api/resume/current").json()
    assert r == {"hash": h, "ready": True, "pages": 2, "pdf_url": f"/api/resume/current.pdf?hash={h}",
                 "page_urls": [f"/api/resume/current/pages/1.png?hash={h}",
                               f"/api/resume/current/pages/2.png?hash={h}"], "error": None}
    assert ctx.spawned == []
    pdf = ctx.client.get(f"/api/resume/current.pdf?hash={h}")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert ctx.client.get("/api/resume/current.pdf").status_code == 200
    png = ctx.client.get("/api/resume/current/pages/2.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert ctx.client.get("/api/resume/current/pages/3.png").status_code == 404
    assert ctx.client.get("/api/resume/current/pages/1.png?hash=../../etc").status_code == 404
    assert ctx.client.get(f"/api/resume/current?hash={h}").json()["ready"] is True
    assert json.loads(ctx.client.get("/api/resume/current?hash=0000000000000000").text)["ready"] is False


def test_current_resume_missing_latex_dir(ctx, monkeypatch, tmp_path):
    monkeypatch.setenv("LATEX_DIR", str(tmp_path / "nope"))
    get_env.cache_clear()
    r = ctx.client.get("/api/resume/current").json()
    assert r["ready"] is False and r["hash"] is None and "not found" in r["error"]


def test_list_all_tailorings(ctx):
    tid = _finished(ctx)
    rows = ctx.client.get("/api/tailorings").json()
    assert rows[0]["id"] == tid and rows[0]["status"] == "done"
    assert rows[0]["job_title"] and rows[0]["resume_pdf"] == f"/api/tailorings/{tid}/resume.pdf"
    assert rows[0]["thumbnail"].endswith("/pages/resume/1.png")
    assert rows[0]["applied_application_id"] is None
    assert ctx.client.get("/api/tailorings", params={"q": "zzz-no-match"}).json() == []
