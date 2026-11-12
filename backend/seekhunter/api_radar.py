"""Company Radar endpoints (mounted by api.create_app via `app.include_router(router)`)."""

import logging
import os
import secrets
import subprocess
import sys
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlmodel import Session

from seekhunter import radar, repo
from seekhunter.db import get_session
from seekhunter.models import RadarCompany
from seekhunter.security import require_write
from seekhunter.sources.ats import ATS_KINDS, build_ats_clients, radar_http_client
from seekhunter.sources.ats.workday import parse_token

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/radar", tags=["radar"])
write = [Depends(require_write)]  # noqa: B008

WEBHOOK_SECRET_ENV = "RADAR_WEBHOOK_SECRET"


class RadarCompanyOut(BaseModel):
    id: int
    name: str
    company_key: str
    ats: str
    ats_token: str | None
    careers_url: str | None
    city: str | None
    enabled: bool
    source: str
    last_checked_at: datetime | None
    last_error: str | None
    last_job_count: int | None
    created_at: datetime


class RadarCompanyIn(BaseModel):
    name: str
    careers_url: str | None = None
    city: str | None = None


class RadarCompanyPatch(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    ats: str | None = None
    ats_token: str | None = None
    careers_url: str | None = None
    city: str | None = None


def _out(c: RadarCompany) -> RadarCompanyOut:
    return RadarCompanyOut(**c.model_dump(exclude={"ignored_ids"}))


def _spawn_cli(*args: str) -> None:
    subprocess.Popen([sys.executable, "-m", "seekhunter.cli", *args], start_new_session=True)


def _radar_http():  # noqa: ANN202  (patched in tests)
    return radar_http_client()


def _get(session: Session, cid: int) -> RadarCompany:
    c = session.get(RadarCompany, cid)
    if c is None:
        raise HTTPException(404, "radar company not found")
    return c


@router.get("/companies", response_model=list[RadarCompanyOut])
def list_companies(enabled: bool | None = None, session: Session = Depends(get_session)):  # noqa: B008
    rows = radar.list_companies(session)
    return [_out(c) for c in rows if enabled is None or c.enabled == enabled]


@router.post("/companies", response_model=RadarCompanyOut, status_code=201, dependencies=write)
def add_company(body: RadarCompanyIn, session: Session = Depends(get_session)):  # noqa: B008
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "name is required")
    url = (body.careers_url or "").strip() or None
    if url and not url.startswith(("http://", "https://")):
        raise HTTPException(422, "careers_url must be an http(s) URL")
    http = _radar_http()
    return _out(radar.add_company(session, name, url, http, build_ats_clients(http), city=body.city))


@router.patch("/companies/{cid}", response_model=RadarCompanyOut, dependencies=write)
def patch_company(cid: int, body: RadarCompanyPatch, session: Session = Depends(get_session)):  # noqa: B008
    c = _get(session, cid)
    fields = body.model_dump(exclude_unset=True)
    if "ats" in fields and fields["ats"] not in ATS_KINDS:
        raise HTTPException(422, f"ats must be one of {', '.join(ATS_KINDS)}")
    ats = fields.get("ats", c.ats)
    token = fields.get("ats_token", c.ats_token)
    if ats == "workday" and token:
        try:
            parse_token(token)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, str(e)) from e
    for key, value in fields.items():
        setattr(c, key, value.strip() if isinstance(value, str) else value)
    if "name" in fields:
        from seekhunter.domain import company_key

        c.company_key = company_key(c.name)
    if {"ats", "ats_token", "careers_url"} & set(fields):
        c.last_error = None
        c.ignored_ids = []
    session.add(c)
    session.commit()
    session.refresh(c)
    return _out(c)


@router.delete("/companies/{cid}", dependencies=write)
def delete_company(cid: int, session: Session = Depends(get_session)) -> dict:  # noqa: B008
    session.delete(_get(session, cid))
    session.commit()
    return {"deleted": True}


@router.post("/companies/{cid}/check", status_code=202, dependencies=write)
def check_company(cid: int, session: Session = Depends(get_session)) -> dict:  # noqa: B008
    c = _get(session, cid)
    if c.ats not in radar.POLLED_ATS:
        raise HTTPException(409, f"{c.ats} careers pages are watched by changedetection.io, not polled")
    _spawn_cli("radar", "--company", str(c.id))
    return {"started": True, "company_id": c.id}


@router.post("/seed", status_code=202, dependencies=write)
def seed() -> dict:
    _spawn_cli("radar", "--seed")
    return {"started": True}


def _webhook_secret_ok(given: str | None) -> bool:
    expected = os.environ.get(WEBHOOK_SECRET_ENV, "")
    if not expected:
        raise HTTPException(503, "radar webhook disabled (RADAR_WEBHOOK_SECRET not set)")
    return bool(given) and secrets.compare_digest(given.encode(), expected.encode())


@router.post("/webhook/changedetection", status_code=202)
async def changedetection_webhook(
    request: Request,
    secret: str | None = Query(default=None),
    x_radar_secret: str | None = Header(default=None),
    session: Session = Depends(get_session),  # noqa: B008
) -> dict:
    """changedetection.io (apprise json://) -> new radar jobs from the careers-page diff. Auth is
    the shared secret (query `secret` or `X-Radar-Secret` header), compared in constant time."""
    if not _webhook_secret_ok(x_radar_secret or secret):
        raise HTTPException(401, "bad secret")
    try:
        payload = await request.json()
    except ValueError:
        payload = {"message": (await request.body()).decode("utf-8", "replace")}
    if not isinstance(payload, dict):
        raise HTTPException(422, "expected a JSON object")
    parsed = radar.parse_changedetection(payload)
    company = radar.match_company_by_url(session, parsed.url or "")
    if company is None:
        log.warning("changedetection webhook for unknown url %s", parsed.url)
        return {"matched": False, "url": parsed.url, "created": 0, "job_ids": []}
    roles = radar.extract_roles(parsed.text, repo.load_settings(session), base_url=company.careers_url)
    created = radar.ingest_webhook(session, company, roles, parsed.url or company.careers_url or "")
    if created:
        _spawn_cli("radar", "--pending")
    return {"matched": True, "company_id": company.id, "created": len(created),
            "job_ids": [j.id for j in created]}
