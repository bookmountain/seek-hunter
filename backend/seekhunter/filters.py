import re
from dataclasses import dataclass, field

from seekhunter.domain import JobData
from seekhunter.settings_model import AppSettings
from seekhunter.skills import extract_skills

_PRE_NEGATION = re.compile(r"\b(no|not)\s+(?:[\w/-]+\s+){0,2}$", re.IGNORECASE)
_POST_NEGATION = re.compile(
    r"^[\s:,\-–—]*(is\s+|are\s+)?not\s+(required|needed|necessary|essential|mandatory)",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"[.!?;:\n•|,–—]")


@dataclass
class FilterResult:
    excluded: bool
    reasons: list[str] = field(default_factory=list)
    snippets: dict[str, str] = field(default_factory=dict)


def _negated(text: str, start: int, end: int) -> bool:
    pre = text[max(0, start - 30) : start]
    breaks = list(_SENTENCE_BREAK.finditer(pre))
    if breaks:
        pre = pre[breaks[-1].end() :]
    post = text[end : end + 30]
    return bool(_PRE_NEGATION.search(pre) or _POST_NEGATION.search(post))


def _first_hit(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            if not _negated(text, m.start(), m.end()):
                return text[max(0, m.start() - 40) : m.end() + 40].strip()
    return None


def _employer_hit(names: list[str], company: str) -> str | None:
    for name in names:
        # Short acronyms (ANZ, CBA, NAB) only count at the start: "Allume ANZ" means Australia/NZ.
        lead = r"^\s*" if name.isupper() and len(name) <= 4 else r"(?<![A-Za-z0-9])"
        if re.search(lead + re.escape(name) + r"(?![A-Za-z0-9])", company, re.IGNORECASE):
            return company
    return None


def bank_hit(job: JobData, settings: AppSettings) -> str | None:
    """Snippet when the employer is a bank (by name) or the ad says it's for a bank, else None."""
    if _employer_hit(settings.employer_allowlist, job.company):
        return None
    return _employer_hit(settings.bank_employers, job.company) or _first_hit(
        settings.bank_keywords, f"{job.title}\n{job.filter_text}")


def evaluate_exclusions(job: JobData, settings: AppSettings) -> FilterResult:
    text = f"{job.title}\n{job.filter_text}"
    result = FilterResult(excluded=False)

    def add(reason: str, snippet: str | None) -> None:
        if snippet:
            result.reasons.append(reason)
            result.snippets[reason] = snippet

    add("clearance", _first_hit(settings.clearance_patterns, text))
    add("citizenship", _first_hit(settings.citizenship_patterns, text))

    allowlisted = _employer_hit(settings.employer_allowlist, job.company) is not None
    if not allowlisted:
        add("defence", _employer_hit(settings.defence_employers, job.company)
            or _first_hit(settings.defence_keywords, text))
        if settings.exclude_banks:
            add("bank", bank_hit(job, settings))
        else:
            hit = _employer_hit(settings.bank_excluded_employers, job.company)
            add("bank", f"{hit} (Westpac Group can't directly hire student visa holders)" if hit else None)
        if settings.exclude_fintech:
            add("fintech", _first_hit(settings.fintech_keywords, text))

    if settings.exclude_off_topic and not result.reasons:
        add("off_topic", _off_topic(job, settings))

    result.excluded = bool(result.reasons)
    return result


def _off_topic(job: JobData, settings: AppSettings) -> str | None:
    """Snippet explaining why the job isn't IT/software, or None when it is on-topic."""
    title = job.title or ""
    if any(re.search(p, title, re.IGNORECASE) for p in settings.it_title_patterns):
        return None
    skills = extract_skills(f"{title} {job.text}")
    if len(skills) >= settings.off_topic_min_skills:
        return None
    found = ", ".join(sorted(skills)) or "none"
    return f"Not an IT/software role: title '{title[:80]}', tech skills in ad: {found}"
