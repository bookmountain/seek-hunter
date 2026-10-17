"""Resume-Matcher client against a mocked HTTP transport. Response bodies follow RM's real schemas
(`apps/backend/app/schemas/models.py`): ResumeUploadResponse, JobUploadResponse, ImproveResumeResponse,
ATSScoreRecord, GenerateContentResponse, GenerateInterviewPrepResponse, StatusResponse."""

import json

import httpx
import pytest

from seekhunter.config import Env
from seekhunter.resume_matcher import ResumeMatcher, RMError, client_from_env

BASE = "http://rm.test"


def _client(handler) -> tuple[ResumeMatcher, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return ResumeMatcher(BASE, transport=httpx.MockTransport(wrapped)), seen


def test_client_from_env_disabled_when_url_empty():
    assert client_from_env(Env(rm_base_url="")) is None
    c = client_from_env(Env(rm_base_url="http://x:3100/"))
    assert c is not None and c.base_url == "http://x:3100"


def test_status():
    c, seen = _client(lambda r: httpx.Response(200, json={
        "status": "setup_required", "llm_configured": False, "llm_healthy": False, "agent_mode": False,
        "has_master_resume": False, "database_stats": {}}))
    assert c.status()["llm_configured"] is False
    assert seen[0].url == f"{BASE}/api/v1/status"


def test_upload_resume_sends_multipart_pdf(tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    c, seen = _client(lambda r: httpx.Response(200, json={
        "message": "ok", "request_id": "r", "resume_id": "m1", "processing_status": "ready",
        "is_master": True, "is_default_master": False}))
    out = c.upload_resume(pdf, "Book_Sam_Resume.pdf")
    assert out["resume_id"] == "m1" and out["processing_status"] == "ready"
    req = seen[0]
    assert req.method == "POST" and req.url.path == "/api/v1/resumes/upload"
    body = req.content
    assert b'name="file"; filename="Book_Sam_Resume.pdf"' in body and b"application/pdf" in body
    assert b"%PDF-1.4 fake" in body


def test_set_default_and_delete():
    c, seen = _client(lambda r: httpx.Response(200, json={"resume_id": "m1", "is_default_master": True}
                                               if r.method == "POST" else {"message": "deleted"}))
    assert c.set_default("m1")["is_default_master"] is True
    c.delete_resume("m0")
    assert [(r.method, r.url.path) for r in seen] == [("POST", "/api/v1/resumes/m1/default"),
                                                      ("DELETE", "/api/v1/resumes/m0")]


def test_list_resumes():
    c, seen = _client(lambda r: httpx.Response(200, json={"request_id": "x", "data": [
        {"resume_id": "m1", "is_master": True, "is_default_master": True, "created_at": "",
         "updated_at": ""}]}))
    assert c.list_resumes()[0]["resume_id"] == "m1"
    assert seen[0].url.params["include_master"] == "true"


def test_upload_job_returns_first_job_id():
    c, seen = _client(lambda r: httpx.Response(200, json={"message": "data successfully processed",
                                                         "job_id": ["j1"], "request": {}}))
    assert c.upload_job("We need React.", "m1") == "j1"
    assert json.loads(seen[0].content) == {"job_descriptions": ["We need React."], "resume_id": "m1"}


def test_improve_returns_data_payload():
    payload = {"request_id": "q", "data": {
        "request_id": "q", "resume_id": "t1", "job_id": "j1", "resume_preview": {"summary": "x"},
        "improvements": [], "outreach_message": None, "interview_prep": None,
        "ats_score": {"overall_score": 71.5, "sub_scores": {"keyword_match": 60.0},
                      "missing_keywords": ["Go"], "injectable_keywords": [], "recommendations": []},
        "warnings": []}}
    c, seen = _client(lambda r: httpx.Response(200, json=payload))
    data = c.improve("m1", "j1")
    assert data["resume_id"] == "t1" and data["ats_score"]["overall_score"] == 71.5
    assert json.loads(seen[0].content) == {"resume_id": "m1", "job_id": "j1"}


def test_ats_score_get_returns_record_or_none():
    record = {"score": {"overall_score": 80.0, "sub_scores": {}, "missing_keywords": [],
                        "injectable_keywords": [], "recommendations": []},
              "calculated_at": "2026-10-18T00:00:00"}
    c, _ = _client(lambda r: httpx.Response(200, json=record))
    assert c.ats_score("t1")["score"]["overall_score"] == 80.0
    c, _ = _client(lambda r: httpx.Response(200, content=b"null"))
    assert c.ats_score("t1") is None
    c, _ = _client(lambda r: httpx.Response(200))
    assert c.ats_score("t1") is None


def test_interview_prep_and_outreach():
    prep = {"role_fit_analysis": ["fit"], "resume_questions": [
        {"question": "Q1?", "focus_area": "React", "suggested_answer_points": ["a"]}],
        "project_follow_ups": [], "skill_gaps": [], "talking_points": []}

    def handler(r):
        if r.url.path.endswith("generate-interview-prep"):
            return httpx.Response(200, json={"interview_prep": prep, "message": "ok"})
        return httpx.Response(200, json={"content": "Hi Brayden", "message": "ok"})

    c, seen = _client(handler)
    assert c.interview_prep("t1")["resume_questions"][0]["question"] == "Q1?"
    assert c.outreach("t1") == "Hi Brayden"
    assert [r.url.path for r in seen] == ["/api/v1/resumes/t1/generate-interview-prep",
                                         "/api/v1/resumes/t1/generate-outreach"]


def test_get_job():
    c, _ = _client(lambda r: httpx.Response(200, json={"job_id": "j1", "content": "x",
                                                      "job_keywords": {"required_skills": ["React"]}}))
    assert c.get_job("j1")["job_keywords"]["required_skills"] == ["React"]


def test_http_error_carries_detail():
    c, _ = _client(lambda r: httpx.Response(409, json={"detail": "You can keep up to 5 master resumes."}))
    with pytest.raises(RMError) as e:
        c.set_default("m1")
    assert e.value.status == 409 and "5 master resumes" in str(e.value)


def test_connection_error_is_rm_error():
    def boom(r):
        raise httpx.ConnectError("refused")

    c, _ = _client(boom)
    with pytest.raises(RMError) as e:
        c.status()
    assert e.value.status is None and "refused" in str(e.value)
