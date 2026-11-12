"""Application funnel: applied -> responded -> interview -> offer, overall and broken down.

Stages are "reached" if the application is in that stage now or ever passed through it (stage-change
events), so an application that went interview -> rejected still counts as an interview.
- responded: reached screening, interview, offer or rejected (any answer from the other side), or a
  reply was logged (LinkedIn reply or meeting with its contact after applying).
- interview: reached interview or offer. offer: reached offer.
Breakdowns: source (seek/jora/linkedin/indeed/radar; manual = added outside SeekHunter), agency vs
direct employer (settings.agency_keywords), work type, and whether the recruiter was called before
or at applying (a `call` logged with its contact up to a day after applying).
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlmodel import Session

from seekhunter import repo
from seekhunter.domain import is_agency
from seekhunter.followups import REPLY_KINDS, Index, load_index
from seekhunter.models import Application

RESPONDED_STAGES = {"screening", "interview", "offer", "rejected"}
INTERVIEW_STAGES = {"interview", "offer"}
CALL_GRACE = timedelta(days=1)
SOURCE_ORDER = ("seek", "jora", "linkedin", "indeed", "radar", "manual")
CALL_ORDER = ("called", "voicemail", "not called")
WORK_TYPE_ORDER = ("part_time", "contract", "casual", "full_time", "unknown")


@dataclass
class Row:
    label: str
    applied: int = 0
    responded: int = 0
    interview: int = 0
    offer: int = 0

    @property
    def response_rate(self) -> float | None:
        return round(self.responded / self.applied, 3) if self.applied else None

    @property
    def interview_rate(self) -> float | None:
        return round(self.interview / self.applied, 3) if self.applied else None

    def as_dict(self) -> dict:
        return {**asdict(self), "response_rate": self.response_rate, "interview_rate": self.interview_rate}


@dataclass
class Outcome:
    responded: bool
    interview: bool
    offer: bool


def _reached(idx: Index, app: Application) -> set[str]:
    stages = {app.stage}
    for ev in idx.events.get(app.id, []):
        if ev.to_stage:
            stages.add(ev.to_stage)
    return stages


def outcome(idx: Index, app: Application) -> Outcome:
    stages = _reached(idx, app)
    replied = any(i.kind in REPLY_KINDS and i.at >= app.applied_at for i in idx.interactions_for(app))
    interview = bool(stages & INTERVIEW_STAGES)
    return Outcome(responded=bool(stages & RESPONDED_STAGES) or replied or interview, interview=interview,
                   offer="offer" in stages)


def source_of(idx: Index, app: Application) -> str:
    job = idx.jobs.get(app.job_id) if app.job_id else None
    return job.source if job else "manual"


def work_type_of(idx: Index, app: Application) -> str:
    job = idx.jobs.get(app.job_id) if app.job_id else None
    return job.work_type if job and job.work_type else "unknown"


def call_bucket(idx: Index, app: Application) -> str:
    """called | voicemail (only voicemails left) | not called — up to a day after applying."""
    limit = app.applied_at + CALL_GRACE
    kinds = {i.kind for i in idx.interactions_for(app) if i.at <= limit}
    if "call" in kinds:
        return "called"
    if "voicemail" in kinds:
        return "voicemail"
    return "not called"


def _group(apps: list[Application], outcomes: dict[int, Outcome], key: Callable[[Application], str],
           order: tuple[str, ...] = ()) -> list[dict]:
    rows: dict[str, Row] = {}
    for a in apps:
        label = key(a)
        row = rows.setdefault(label, Row(label=label))
        o = outcomes[a.id]
        row.applied += 1
        row.responded += o.responded
        row.interview += o.interview
        row.offer += o.offer
    rank = {v: i for i, v in enumerate(order)}
    ordered = sorted(rows.values(), key=lambda r: (rank.get(r.label, len(rank)), -r.applied, r.label))
    return [r.as_dict() for r in ordered]


def funnel(session: Session, since: datetime | None = None) -> dict:
    settings = repo.load_settings(session)
    idx = load_index(session)
    apps = [a for a in idx.applications if since is None or a.applied_at >= since]
    outcomes = {a.id: outcome(idx, a) for a in apps}
    total = _group(apps, outcomes, lambda a: "all")

    def employer(a: Application) -> str:
        return "agency" if is_agency(a.company, settings.agency_keywords) else "direct"

    return {
        "total": total[0] if total else Row(label="all").as_dict(),
        "by_source": _group(apps, outcomes, lambda a: source_of(idx, a), SOURCE_ORDER),
        "by_employer": _group(apps, outcomes, employer, ("agency", "direct")),
        "by_work_type": _group(apps, outcomes, lambda a: work_type_of(idx, a), WORK_TYPE_ORDER),
        "by_call": _group(apps, outcomes, lambda a: call_bucket(idx, a), CALL_ORDER),
    }
