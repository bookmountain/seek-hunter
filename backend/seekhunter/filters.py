import re
from dataclasses import dataclass, field

from seekhunter.domain import JobData
from seekhunter.settings_model import AppSettings

_PRE_NEGATION = re.compile(r"\b(no|not|without|non)\b", re.IGNORECASE)
_POST_NEGATION = re.compile(r"^\W*(is\s+|are\s+)?not\s+(required|needed|necessary)", re.IGNORECASE)
_SENTENCE_BREAK = re.compile(r"[.!?\n]")


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
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", company, re.IGNORECASE):
            return company
    return None


def evaluate_exclusions(job: JobData, settings: AppSettings) -> FilterResult:
    text = f"{job.title}\n{job.text}"
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
        add("bank", _employer_hit(settings.bank_employers, job.company)
            or _first_hit(settings.bank_keywords, text))
        if settings.exclude_fintech:
            add("fintech", _first_hit(settings.fintech_keywords, text))

    result.excluded = bool(result.reasons)
    return result
