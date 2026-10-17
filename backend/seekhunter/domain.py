import re
from dataclasses import dataclass
from datetime import datetime

from selectolax.lexbor import LexborHTMLParser

WORK_TYPES = ("full_time", "part_time", "contract", "casual", "unknown")
FLEXIBLE_WORK_TYPES = {"part_time", "contract", "casual"}

_COMPANY_SUFFIXES = re.compile(r"\b(pty|ltd|limited|inc|group|australia|au|sa|nsw|vic|qld|wa|tas|act|nt)\b")

APPLICATION_STAGES = ("applied", "screening", "interview", "offer", "rejected", "withdrawn", "no_response")
INTERACTION_KINDS = ("call", "email", "linkedin_invite", "linkedin_accepted", "linkedin_message", "meeting",
                     "note")
APPLICATION_EVENT_KINDS = ("created", "stage_changed", "note")


def normalize_work_type(label: str | None) -> str:
    text = (label or "").lower()
    if "casual" in text:
        return "casual"
    if "contract" in text or "temp" in text:
        return "contract"
    if "part" in text:
        return "part_time"
    if "full" in text:
        return "full_time"
    return "unknown"


def html_to_text(html: str) -> str:
    if not html:
        return ""
    text = LexborHTMLParser(html).text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def html_to_lines(html: str) -> str:
    if not html:
        return ""
    text = LexborHTMLParser(html).text(separator="\n")
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def company_key(company: str) -> str:
    """Normalises a company name for matching/grouping: lowercase, suffixes (pty/ltd/state names/etc.)
    and punctuation stripped. Used both for job deduping (`dedupe_key`) and for application/contact
    grouping ("has this company already got my resume?")."""
    company_clean = _COMPANY_SUFFIXES.sub(" ", (company or "").lower())
    return _norm(company_clean)


def dedupe_key(title: str, company: str) -> str:
    return f"{_norm(title)}|{company_key(company)}"


@dataclass
class JobData:
    source: str
    external_id: str
    title: str
    company: str
    location: str
    work_type: str
    url: str
    salary_label: str | None = None
    listed_at: datetime | None = None
    teaser: str = ""
    description_html: str = ""
    contact_phone: str | None = None
    contact_email: str | None = None
    applicant_count: int | None = None
    applicant_volume: str | None = None
    resume_pct: int | None = None
    cover_letter_pct: int | None = None

    @property
    def text(self) -> str:
        return html_to_text(self.description_html) or self.teaser

    @property
    def filter_text(self) -> str:
        return html_to_lines(self.description_html) or self.teaser
