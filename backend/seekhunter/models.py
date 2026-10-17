from datetime import UTC, datetime

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Naive UTC. SQLite drops tzinfo, so the whole app stores and compares naive UTC datetimes."""
    return datetime.now(UTC).replace(tzinfo=None)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    external_id: str
    title: str
    company: str = ""
    location: str = ""
    city: str | None = Field(default=None, index=True)
    work_type: str = "unknown"
    salary_label: str | None = None
    listed_at: NaiveDatetime | None = None
    url: str
    teaser: str = ""
    description_html: str = ""
    dedupe_key: str = Field(index=True)
    canonical_job_id: int | None = Field(default=None, index=True)
    first_seen_at: NaiveDatetime = Field(default_factory=utcnow, index=True)
    status: str = "new"
    notes: str = ""
    force_include: bool = False
    notified_at: NaiveDatetime | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    contact_linkedin: str | None = None
    applicant_count: int | None = None
    applicant_volume: str | None = None
    resume_pct: int | None = None
    cover_letter_pct: int | None = None
    insights_checked_at: NaiveDatetime | None = None


class JobEvaluation(SQLModel, table=True):
    __tablename__ = "job_evaluations"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", unique=True, index=True)
    excluded: bool = False
    reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    snippets: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    rule_score: int = 0
    llm_score: int | None = None
    llm_note: str | None = None
    llm_provider: str | None = None
    final_score: int = 0
    matched_skills: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    flags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class SearchProfile(SQLModel, table=True):
    __tablename__ = "search_profiles"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    keywords: str
    location: str = "All Adelaide SA"
    work_types: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    sources: list[str] = Field(default_factory=lambda: ["seek", "jora", "linkedin"], sa_column=Column(JSON))
    enabled: bool = True


class SettingsRow(SQLModel, table=True):
    __tablename__ = "settings"

    id: int = Field(default=1, primary_key=True)
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Run(SQLModel, table=True):
    __tablename__ = "runs"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = "crawl"  # crawl | recap | alert
    started_at: NaiveDatetime = Field(default_factory=utcnow, index=True)
    finished_at: NaiveDatetime | None = None
    source_status: dict = Field(default_factory=dict, sa_column=Column(JSON))
    new_jobs: int = 0
    notified: int = 0
    llm_provider: str | None = None
    error: str | None = None


class Outbox(SQLModel, table=True):
    __tablename__ = "outbox"

    id: int | None = Field(default=None, primary_key=True)
    text: str
    attempts: int = 0
    last_error: str | None = None
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    sent_at: NaiveDatetime | None = None


class MarketJob(SQLModel, table=True):
    __tablename__ = "market_jobs"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(default="seek", index=True)
    external_id: str
    city: str = Field(index=True)
    keyword: str = ""
    title: str
    company: str = ""
    work_type: str = "unknown"
    salary_label: str | None = None
    salary_min_hourly: float | None = None
    salary_max_hourly: float | None = None
    listed_at: NaiveDatetime | None = None
    role_family: str = "other"
    skills: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    details_fetched: bool = False
    first_seen_at: NaiveDatetime = Field(default_factory=utcnow, index=True)
    last_seen_at: NaiveDatetime = Field(default_factory=utcnow, index=True)


class MarketSnapshot(SQLModel, table=True):
    __tablename__ = "market_snapshots"
    __table_args__ = (UniqueConstraint("city", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    city: str = Field(index=True)
    date: NaiveDatetime = Field(index=True)
    total: int = 0
    detailed_count: int = 0
    by_work_type: dict = Field(default_factory=dict, sa_column=Column(JSON))
    by_role_family: dict = Field(default_factory=dict, sa_column=Column(JSON))
    skill_counts: dict = Field(default_factory=dict, sa_column=Column(JSON))
    salary_percentiles: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Tailoring(SQLModel, table=True):
    __tablename__ = "tailorings"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    status: str = "queued"  # queued | running | done | failed
    progress: str = ""
    created_at: NaiveDatetime = Field(default_factory=utcnow, index=True)
    started_at: NaiveDatetime | None = None
    finished_at: NaiveDatetime | None = None
    provider: str | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # {"base": ResumeDoc, "tailored": ResumeDoc, "keywords_matched", "gaps", "cover_letter", "pages"}
    result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    resume_hash: str | None = None
    out_dir: str | None = None
    send_requested: bool = False
    sent_at: NaiveDatetime | None = None


class Application(SQLModel, table=True):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id"),)

    id: int | None = Field(default=None, primary_key=True)
    job_id: int | None = Field(default=None, foreign_key="jobs.id", index=True)
    company: str = ""
    company_key: str = Field(index=True)
    title: str = ""
    url: str | None = None
    location: str | None = None
    applied_at: NaiveDatetime = Field(default_factory=utcnow, index=True)
    tailoring_id: int | None = Field(default=None, foreign_key="tailorings.id")
    stage: str = "applied"
    source: str = "seekhunter"  # seekhunter | manual
    notes: str = ""
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    updated_at: NaiveDatetime = Field(default_factory=utcnow)


class Contact(SQLModel, table=True):
    __tablename__ = "contacts"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    company: str = ""
    company_key: str = Field(index=True)
    role: str | None = None
    phone: str | None = None
    email: str | None = None
    linkedin: str | None = None
    notes: str = ""
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    updated_at: NaiveDatetime = Field(default_factory=utcnow)


class ContactJob(SQLModel, table=True):
    __tablename__ = "contact_jobs"
    __table_args__ = (UniqueConstraint("contact_id", "job_id"),)

    id: int | None = Field(default=None, primary_key=True)
    contact_id: int = Field(foreign_key="contacts.id", index=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Interaction(SQLModel, table=True):
    __tablename__ = "interactions"

    id: int | None = Field(default=None, primary_key=True)
    contact_id: int | None = Field(default=None, foreign_key="contacts.id", index=True)
    application_id: int | None = Field(default=None, foreign_key="applications.id", index=True)
    kind: str  # call | email | linkedin_invite | linkedin_accepted | linkedin_message | meeting | note
    at: NaiveDatetime = Field(default_factory=utcnow, index=True)
    note: str = ""
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class ApplicationEvent(SQLModel, table=True):
    __tablename__ = "application_events"

    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="applications.id", index=True)
    kind: str  # created | stage_changed | note
    from_stage: str | None = None
    to_stage: str | None = None
    at: NaiveDatetime = Field(default_factory=utcnow, index=True)
    note: str = ""
