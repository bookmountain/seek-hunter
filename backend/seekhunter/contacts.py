import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

log = logging.getLogger(__name__)

_NAME_WORD = r"[A-Z][a-zA-Z'’-]+"
_NAME = rf"{_NAME_WORD}(?:\s+{_NAME_WORD}){{1,2}}"
_VERB = r"(?:call|contact|speak(?:\s+(?:to|with))?|reach out to|email|chat(?:\s+(?:to|with))?)"

_NAME_PATTERNS = (
    re.compile(rf"\b(?i:{_VERB})\s+({_NAME})\b"),
    re.compile(rf"\b({_NAME})\s+(?:on|at)\s+(?=(?:\+61|\(?0[2-478]\)?|1[38]00)[\s\d()-]{{6,}})"),
    re.compile(rf"\b({_NAME}),\s+(?:Senior\s+|Principal\s+|Lead\s+)?(?:[A-Z][a-z]+\s+)?"
               r"(?:Consultant|Recruiter|Manager|Partner|Director|Specialist|Associate|Advisor|Adviser)\b"),
)

_NAME_BLOCKLIST = {
    "pty", "ltd", "group", "team", "recruitment", "talent", "australia", "seek", "us", "hr",
    # roles / org words
    "lead", "leader", "manager", "management", "delivery", "automation", "developer", "engineer",
    "engineering", "consultant", "officer", "director", "head", "senior", "principal", "services",
    "service", "solutions", "department", "government", "university", "council", "office", "support",
    "desk", "operations", "digital", "technology", "technologies", "it", "ict", "people", "careers",
    "acquisition", "resourcing", "partner", "partners", "client", "clients", "company", "agency",
    # tech words that look capitalised in ads
    "azure", "api", "apis", "aws", "cloud", "data", "java", "python", "react", "net", "sql",
    # places
    "adelaide", "hill", "park", "terrace", "street", "road", "cbd", "north", "south", "east", "west",
    "sa", "nsw", "vic", "qld", "wa", "tas", "act", "nt", "lakes", "beach", "valley", "heights",
    # places / subjects that look like names
    "st", "saint", "mount", "mt", "port", "new", "united", "kingdom", "states", "zealand", "wales",
    "sydney", "melbourne", "brisbane", "perth", "hobart", "darwin", "canberra", "london", "singapore",
    "india", "leonards", "computer", "science", "sciences", "information", "systems", "business",
    "bachelor", "master", "masters", "degree", "college", "institute",
    # sentence words
    "the", "our", "a", "an", "apply", "today", "now", "please", "click", "for", "and", "or", "on", "at",
}

_LANDLINE_RE = re.compile(r"(\+61[\s-]?|0)([2378])[\s-]?(\d{4})[\s-]?(\d{4})\b")
_MOBILE_RE = re.compile(r"(\+61[\s-]?|0)4(\d{2})[\s-]?(\d{3})[\s-]?(\d{3})\b")
_FREECALL_RE = re.compile(r"\b(1[38]00)[\s-]?(\d{3})[\s-]?(\d{3})\b")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_GENERIC_LOCAL_PART = re.compile(r"^(no[-._]?reply|do[-._]?not[-._]?reply)$", re.IGNORECASE)

_LINKEDIN_PROFILE_RE = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^/?#\s\"]+", re.IGNORECASE
)


@dataclass
class Contacts:
    name: str | None = None
    phone: str | None = None
    email: str | None = None


def _valid_name(name: str) -> bool:
    words = name.split()
    if len(words) < 2:
        return False
    if any(w.isupper() and len(w) > 1 for w in words):  # acronyms like "IT", "ICT", "API"
        return False
    return not any(w.strip("'’").lower() in _NAME_BLOCKLIST for w in words)


def is_plausible_name(name: str | None, title: str = "", company: str = "") -> bool:
    """Public check used when reconciling stored names (e.g. backfill)."""
    if not name or not _valid_name(name):
        return False
    lowered = name.lower()
    return lowered not in title.lower() and lowered not in company.lower()


def _extract_name(text: str) -> str | None:
    for pattern in _NAME_PATTERNS:
        for match in pattern.finditer(text):
            candidate = match.group(1).strip()
            if _valid_name(candidate):
                return candidate
    return None


def _format_landline(m: re.Match) -> str:
    area, rest = m.group(2), f"{m.group(3)} {m.group(4)}"
    return f"0{area} {rest}"


def _format_mobile(m: re.Match) -> str:
    rest = f"4{m.group(2)} {m.group(3)} {m.group(4)}"
    return f"0{rest}"


def _format_freecall(m: re.Match) -> str:
    return f"{m.group(1)} {m.group(2)} {m.group(3)}"


def _extract_phone(text: str) -> str | None:
    candidates = []
    for regex, formatter in (
        (_MOBILE_RE, _format_mobile),
        (_LANDLINE_RE, _format_landline),
        (_FREECALL_RE, _format_freecall),
    ):
        m = regex.search(text)
        if m:
            candidates.append((m.start(), formatter(m)))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def normalize_phone(value: str | None) -> str | None:
    """Normalise a structured phone value (e.g. '+61 8 8306 8208') to local AU format."""
    if not value:
        return value
    return _extract_phone(value) or value.strip()


def _extract_email(text: str) -> str | None:
    for m in _EMAIL_RE.finditer(text):
        local = m.group(0).split("@", 1)[0]
        if not _GENERIC_LOCAL_PART.match(local):
            return m.group(0)
    return None


def extract_contacts(text: str) -> Contacts:
    text = text or ""
    return Contacts(name=_extract_name(text), phone=_extract_phone(text), email=_extract_email(text))


def linkedin_search_urls(name: str | None, company: str) -> dict[str, str]:
    company = company or ""
    if name:
        keywords = f"{name} {company}".strip()
        google_q = f'site:linkedin.com/in "{name}" "{company}"'
    else:
        keywords = f"{company} recruiter".strip()
        google_q = f'site:linkedin.com/in "{company}" recruiter'
    return {
        "linkedin": f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(keywords)}",
        "google": f"https://www.google.com/search?q={quote_plus(google_q)}",
    }


def _default_http_get(url: str, params: dict, headers: dict) -> Any:
    from curl_cffi import requests as cffi_requests

    return cffi_requests.get(url, params=params, headers=headers, timeout=15)


_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_BRAVE_MIN_INTERVAL = 1.1  # free tier: ~1 request/second
_last_brave_call = 0.0


def _brave_search(query: str, api_key: str, http_get: Callable[..., Any],
                  sleep: Callable[[float], None]) -> list[dict]:
    global _last_brave_call
    for attempt in range(2):
        wait = _BRAVE_MIN_INTERVAL - (time.monotonic() - _last_brave_call)
        if wait > 0:
            sleep(wait)
        _last_brave_call = time.monotonic()
        resp = http_get(_BRAVE_URL, params={"q": query, "count": 5},
                        headers={"X-Subscription-Token": api_key, "Accept": "application/json"})
        if getattr(resp, "status_code", 200) == 429 and attempt == 0:
            sleep(2.0)
            continue
        try:
            return resp.json()["web"]["results"] or []
        except (KeyError, TypeError, ValueError):
            return []
    return []


def find_linkedin_profile(
    name: str | None,
    company: str,
    api_key: str | None,
    http_get: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str | None:
    """Best-effort lookup of a recruiter's LinkedIn profile via Brave Search.

    Only returns linkedin.com/in/ URLs whose result title contains both the first and last name."""
    if not name or not api_key:
        return None
    http_get = http_get or _default_http_get
    parts = name.split()
    first, last = parts[0].lower(), parts[-1].lower()
    for query in (f'site:linkedin.com/in "{name}" "{company}"', f"{name} {company} linkedin"):
        try:
            results = _brave_search(query, api_key, http_get, sleep)
        except Exception as e:  # noqa: BLE001  any network/parse failure means "no result"
            log.warning("brave linkedin lookup failed for %r at %r: %s", name, company, e)
            return None
        for r in results:
            url, title = r.get("url") or "", (r.get("title") or "").lower()
            if not _LINKEDIN_PROFILE_RE.match(url):
                continue
            slug = re.sub(r"[^a-z]", "", url.lower().split("/in/", 1)[1])
            title_name = title.split(" - ")[0].split(" | ")[0].strip()
            if title_name == name.lower() or (first in slug and last in slug):
                return url
    return None
