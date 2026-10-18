import re
from dataclasses import dataclass
from datetime import datetime

from selectolax.lexbor import LexborHTMLParser

WORK_TYPES = ("full_time", "part_time", "contract", "casual", "unknown")
FLEXIBLE_WORK_TYPES = {"part_time", "contract", "casual"}

_COMPANY_SUFFIXES = re.compile(r"\b(pty|ltd|limited|inc|group|australia|au|sa|nsw|vic|qld|wa|tas|act|nt)\b")

APPLICATION_STAGES = ("applied", "screening", "interview", "offer", "rejected", "withdrawn", "no_response")
INTERACTION_KINDS = (
    "call",
    "email",
    "linkedin_invite",
    "linkedin_accepted",
    "linkedin_message",
    "meeting",
    "note",
)
APPLICATION_EVENT_KINDS = ("created", "stage_changed", "note")

CITY_BY_PROFILE_LOCATION = {
    "All Adelaide SA": "adelaide",
    "All Melbourne VIC": "melbourne",
    "All Sydney NSW": "sydney",
    "All Perth WA": "perth",
    "All Brisbane QLD": "brisbane",
}
_CITY_NAMES = ("adelaide", "melbourne", "sydney", "perth", "brisbane")


def derive_city_from_location(location: str | None, default: str = "other") -> str:
    """Best-effort city from a free-text job location (e.g. "Adelaide SA"): the first known city
    name found in it, case-insensitively, else `default`."""
    loc = (location or "").lower()
    for city in _CITY_NAMES:
        if city in loc:
            return city
    return default


def derive_city(profile_location: str | None, job_location: str, default: str = "other") -> str:
    """City for a newly-seen job: the search profile's location wins when it's one of the known
    profile locations (e.g. "All Melbourne VIC"); otherwise falls back to parsing the job's own
    `location` text, and finally to `default`."""
    if profile_location and profile_location in CITY_BY_PROFILE_LOCATION:
        return CITY_BY_PROFILE_LOCATION[profile_location]
    return derive_city_from_location(job_location, default=default)


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


_TYPE_LABELED = re.compile(
    r"(?:job|employment|work|position|contract)\s*type\s*[:\-]\s*([a-z /-]{3,40})", re.IGNORECASE
)
_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("casual", re.compile(r"\bcasual\b(?!\s+(dress|attire|environment|culture|vibe))", re.IGNORECASE)),
    (
        "contract",
        re.compile(
            r"\b(contract(or)?\s+(role|position|opportunity|basis)|fixed[- ]term|"
            r"\d+[- ]?(month|mth|week)s?\s+contract|contract\s+(until|to|of)|temporary|temp\b|"
            r"daily rate|day rate|initial\s+\d+\s+months?)",
            re.IGNORECASE,
        ),
    ),
    (
        "part_time",
        re.compile(r"\bpart[- ]time\b|\b0\.\d\s*fte\b|\b[1-3] days? (a|per) week\b", re.IGNORECASE),
    ),
    (
        "full_time",
        re.compile(
            r"\bfull[- ]time\b|\bpermanent\b(?!\s+resid)|\b1\.0\s*fte\b|\b38 hours? (a|per) week\b",
            re.IGNORECASE,
        ),
    ),
]


def infer_work_type(text: str) -> str:
    """Best-effort work type from ad text when the board didn't label it. An explicit
    'Job type: …' label wins; otherwise the most specific signal (casual > contract > part-time >
    full-time) that appears in the ad."""
    if not text:
        return "unknown"
    labeled = _TYPE_LABELED.search(text)
    if labeled:
        kind = normalize_work_type(labeled.group(1))
        if kind != "unknown":
            return kind
    for kind, pattern in _TYPE_PATTERNS:
        if pattern.search(text):
            return kind
    return "unknown"


_STATE_ABBR = {
    "south australia": "SA",
    "victoria": "VIC",
    "new south wales": "NSW",
    "western australia": "WA",
    "queensland": "QLD",
    "tasmania": "TAS",
    "northern territory": "NT",
    "australian capital territory": "ACT",
}


def normalize_location(location: str) -> str:
    """'Adelaide, South Australia, Australia' -> 'Adelaide SA' (LinkedIn style -> SEEK style)."""
    loc = (location or "").strip()
    loc = re.sub(r",?\s*Australia$", "", loc).strip()
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if len(parts) >= 2 and parts[-1].lower() in _STATE_ABBR:
        return f"{', '.join(parts[:-1])} {_STATE_ABBR[parts[-1].lower()]}"
    if len(parts) == 1 and parts[0].lower() in _STATE_ABBR:
        return _STATE_ABBR[parts[0].lower()]
    return loc


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
