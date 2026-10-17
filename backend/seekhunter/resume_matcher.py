"""Small HTTP client for a self-hosted Resume-Matcher (https://github.com/srbhr/Resume-Matcher).

Talks to RM's FastAPI backend under `/api/v1` (directly, or through its Next.js frontend which proxies
the same paths). Shapes follow RM's `app/schemas/models.py`. Disabled when `RM_BASE_URL` is empty.
"""

from pathlib import Path
from typing import Any

import httpx

from seekhunter.config import Env

# LLM-backed calls (resume parse on upload, improve, interview prep) can take minutes.
LLM_TIMEOUT = 600.0
QUICK_TIMEOUT = 30.0


class RMError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ResumeMatcher:
    def __init__(self, base_url: str, *, timeout: float = LLM_TIMEOUT,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=f"{self.base_url}/api/v1", timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, *, quick: bool = False, **kw: Any) -> Any:
        if quick:
            kw["timeout"] = QUICK_TIMEOUT
        try:
            r = self._http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise RMError(f"Resume-Matcher unreachable: {e}") from e
        if r.status_code >= 400:
            detail: Any = r.text
            try:
                body = r.json()
                detail = body.get("detail", body) if isinstance(body, dict) else body
            except ValueError:
                pass
            raise RMError(f"Resume-Matcher {method} {path} -> {r.status_code}: {str(detail)[:500]}",
                          status=r.status_code)
        if not r.content.strip():
            return None
        try:
            return r.json()
        except ValueError as e:
            raise RMError(f"Resume-Matcher {method} {path}: response is not JSON") from e

    # ----------------------------------------------------------------- health
    def status(self) -> dict:
        """StatusResponse: {status, llm_configured, llm_healthy, agent_mode, has_master_resume, ...}."""
        return self._call("GET", "/status", quick=True)

    # ----------------------------------------------------------------- resumes
    def upload_resume(self, pdf: Path, filename: str = "resume.pdf") -> dict:
        """ResumeUploadResponse: {resume_id, processing_status, is_master, is_default_master, ...}.
        RM parses the PDF to structured JSON with its LLM; `processing_status` is "failed" without one."""
        with pdf.open("rb") as fh:
            return self._call("POST", "/resumes/upload", files={"file": (filename, fh, "application/pdf")})

    def set_default(self, resume_id: str) -> dict:
        return self._call("POST", f"/resumes/{resume_id}/default", quick=True)

    def delete_resume(self, resume_id: str) -> dict:
        return self._call("DELETE", f"/resumes/{resume_id}", quick=True)

    def list_resumes(self, include_master: bool = True) -> list[dict]:
        out = self._call("GET", "/resumes/list", quick=True,
                         params={"include_master": "true" if include_master else "false"})
        return list((out or {}).get("data") or [])

    def improve(self, resume_id: str, job_id: str) -> dict:
        """ImproveResumeResponse.data: {resume_id (tailored), job_id, resume_preview, ats_score,
        outreach_message, interview_prep, warnings, ...}."""
        out = self._call("POST", "/resumes/improve", json={"resume_id": resume_id, "job_id": job_id})
        return (out or {}).get("data") or {}

    def ats_score(self, tailored_id: str) -> dict | None:
        """ATSScoreRecord {score: ATSScore, calculated_at}, or None if RM never scored it."""
        return self._call("GET", f"/resumes/{tailored_id}/ats-score", quick=True)

    def recalc_ats_score(self, tailored_id: str) -> dict:
        return self._call("POST", f"/resumes/{tailored_id}/ats-score", quick=True)

    def interview_prep(self, tailored_id: str) -> dict:
        """InterviewPrepData: {role_fit_analysis, resume_questions[{question, focus_area,
        suggested_answer_points}], project_follow_ups, skill_gaps, talking_points}."""
        out = self._call("POST", f"/resumes/{tailored_id}/generate-interview-prep")
        return (out or {}).get("interview_prep") or {}

    def outreach(self, tailored_id: str) -> str:
        return (self._call("POST", f"/resumes/{tailored_id}/generate-outreach") or {}).get("content") or ""

    # ----------------------------------------------------------------- jobs
    def upload_job(self, text: str, resume_id: str | None = None) -> str:
        out = self._call("POST", "/jobs/upload", quick=True,
                         json={"job_descriptions": [text], "resume_id": resume_id})
        ids = (out or {}).get("job_id") or []
        if not ids:
            raise RMError("Resume-Matcher returned no job id")
        return ids[0]

    def get_job(self, job_id: str) -> dict:
        """The stored job; after `improve` it carries `job_keywords` {role, required_skills,
        preferred_skills, keywords, ...} extracted by RM's LLM."""
        return self._call("GET", f"/jobs/{job_id}", quick=True)


def client_from_env(env: Env) -> ResumeMatcher | None:
    url = (env.rm_base_url or "").strip()
    return ResumeMatcher(url) if url else None
