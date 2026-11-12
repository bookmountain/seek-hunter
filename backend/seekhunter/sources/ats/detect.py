"""Which ATS does an employer use? From a careers URL (the URL itself, then links/iframes/scripts
in its HTML) and, failing that, by guessing board tokens from the company name against the
Greenhouse / Lever / Ashby APIs."""

import logging
import re
from dataclasses import dataclass

from seekhunter.sources.ats.base import ATSError, is_australian

log = logging.getLogger(__name__)


@dataclass
class Detection:
    ats: str
    token: str | None
    careers_url: str | None = None


_SKIP_TOKENS = {"embed", "api", "j", "jobs", "v0", "v1", "js", "job_board", "wday", "www", "apply"}
_W = r"[A-Za-z0-9_-]+"
# (ats, pattern, token builder). Order matters: the more specific API/embed forms come first.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("greenhouse", re.compile(rf"boards-api\.greenhouse\.io/v1/boards/({_W})", re.I)),
    ("greenhouse", re.compile(rf"greenhouse\.io/embed/job_board(?:/js)?\?for=({_W})", re.I)),
    ("greenhouse", re.compile(rf"(?:job-)?boards(?:\.eu)?\.greenhouse\.io/({_W})", re.I)),
    ("lever", re.compile(r"api\.lever\.co/v0/postings/([A-Za-z0-9_.-]+)", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)", re.I)),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)", re.I)),
    ("workable", re.compile(rf"apply\.workable\.com/(?:api/v\d/(?:widget/)?accounts/)?({_W})", re.I)),
    ("workable", re.compile(r"\b([a-z0-9-]+)\.workable\.com", re.I)),
    ("smartrecruiters", re.compile(rf"api\.smartrecruiters\.com/v1/companies/({_W})", re.I)),
    ("smartrecruiters", re.compile(rf"(?:jobs|careers)\.smartrecruiters\.com/({_W})", re.I)),
    ("workday", re.compile(
        r"\b([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/[a-z0-9-]+/)?(?:[a-z]{2}-[A-Z]{2}/)?"
        rf"({_W})", re.I)),
    ("pageup", re.compile(r"\b((?:[a-z0-9-]+\.)*pageuppeople\.com/apply/\d+)", re.I)),
]


def detect_from_text(text: str) -> Detection | None:
    """First ATS board reference found in a URL or an HTML page."""
    for ats, pattern in _PATTERNS:
        for m in pattern.finditer(text or ""):
            if ats == "workday":
                tenant, wd, site = m.group(1).lower(), m.group(2).lower(), m.group(3)
                if site.lower() in _SKIP_TOKENS:
                    continue
                return Detection(ats, f"{tenant}.{wd}/{site}")
            token = m.group(1)
            if token.lower() in _SKIP_TOKENS:
                continue
            return Detection(ats, token)
    if re.search(r"pageuppeople\.com|pageup\.com\.au", text or "", re.I):
        return Detection("pageup", None)
    return None


_LEGAL = re.compile(r"\b(pty|ltd|limited|inc|incorporated|llc|plc|co|corp|corporation|the)\b\.?", re.I)


def slug_candidates(name: str) -> list[str]:
    """'Culture Amp Pty Ltd' -> ['cultureamp', 'culture-amp']; too-short slugs are dropped."""
    base = _LEGAL.sub(" ", (name or "").lower().replace("&", " and "))
    words = re.findall(r"[a-z0-9]+", base)
    out = []
    for slug in ("".join(words), "-".join(words)):
        if len(slug) >= 3 and slug not in out:
            out.append(slug)
    return out


@dataclass
class _Probe:
    name: str
    ats_token: str


GUESS_ATS = ("greenhouse", "lever", "ashby")


def guess_board(name: str, clients: dict) -> Detection | None:
    """Tries each slug of `name` on Greenhouse/Lever/Ashby: a board that answers with at least one
    posting, at least one of them in Australia (keeps unrelated same-named boards out), wins."""
    for slug in slug_candidates(name):
        for ats in GUESS_ATS:
            client = clients.get(ats)
            if client is None:
                continue
            try:
                jobs = client.list_jobs(_Probe(name, slug))
            except ATSError:
                continue
            except Exception as e:  # noqa: BLE001  network trouble on one guess shouldn't stop the rest
                log.warning("ats guess %s/%s failed: %s", ats, slug, e)
                continue
            if jobs and any(is_australian(j.location) for j in jobs):
                return Detection(ats, slug)
    return None


def detect_ats(http, clients: dict, name: str | None = None, careers_url: str | None = None,  # noqa: ANN001
               guess: bool = True) -> Detection | None:
    """Detection for a company. With a careers URL the result is never None: an unrecognised
    page comes back as ats "other" (or "pageup") for changedetection.io to watch."""
    url = (careers_url or "").strip() or None
    if url:
        found = detect_from_text(url)
        if found is None or (found.ats == "pageup" and found.token is None):
            try:
                resp = http.get(url)
                if getattr(resp, "status_code", 200) == 200:
                    found = detect_from_text(resp.text) or found
            except Exception as e:  # noqa: BLE001  unreachable careers page: fall back to guessing
                log.warning("careers page %s failed: %s", url, e)
        if found is not None:
            found.careers_url = url
            return found
    if guess and name:
        found = guess_board(name, clients)
        if found is not None:
            found.careers_url = url
            return found
    if url:
        return Detection("other", None, url)
    return None
