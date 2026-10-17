import logging
import re
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
    re.compile(rf"\b({_NAME})\s+(?:on|at)\s+(?=[+(]|\d)"),
    re.compile(rf"\b({_NAME}),\s+[A-Z][a-z]+"),
)

_NAME_BLOCKLIST = {
    "pty", "ltd", "group", "team", "recruitment", "talent", "australia", "seek", "us", "hr",
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
    return not any(w.strip("'’").lower() in _NAME_BLOCKLIST for w in words)


def _extract_name(text: str) -> str | None:
    for pattern in _NAME_PATTERNS:
        for match in pattern.finditer(text):
            candidate = match.group(1).strip()
            if _valid_name(candidate):
                return candidate
    return None


def _format_landline(m: re.Match) -> str:
    prefix, area, rest = m.group(1), m.group(2), f"{m.group(3)} {m.group(4)}"
    return f"+61 {area} {rest}" if prefix.strip().startswith("+61") else f"0{area} {rest}"


def _format_mobile(m: re.Match) -> str:
    prefix, rest = m.group(1), f"4{m.group(2)} {m.group(3)} {m.group(4)}"
    return f"+61 {rest}" if prefix.strip().startswith("+61") else f"0{rest}"


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


def find_linkedin_profile(
    name: str | None,
    company: str,
    api_key: str | None,
    http_get: Callable[..., Any] | None = None,
) -> str | None:
    if not name or not api_key:
        return None
    http_get = http_get or _default_http_get
    query = f'site:linkedin.com/in "{name}" "{company}"'
    try:
        resp = http_get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 5},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        )
        data = resp.json()
    except Exception as e:  # noqa: BLE001  any network/parse failure means "no result"
        log.warning("brave linkedin lookup failed for %r at %r: %s", name, company, e)
        return None
    try:
        results = data["web"]["results"]
    except (KeyError, TypeError):
        return None
    parts = name.split()
    first, last = parts[0].lower(), parts[-1].lower()
    for r in results:
        url, title = r.get("url") or "", (r.get("title") or "").lower()
        if _LINKEDIN_PROFILE_RE.match(url) and first in title and last in title:
            return url
    return None
