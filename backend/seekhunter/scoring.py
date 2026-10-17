import re
from dataclasses import dataclass, field

from seekhunter.domain import FLEXIBLE_WORK_TYPES, JobData
from seekhunter.settings_model import AppSettings
from seekhunter.skills import extract_skills

_HOURS = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*\+?\s*(?:hours|hrs|h)\b\s*(?:per|a|/|each|every)?\s*(week|wk|fortnight|weekly)",
    re.IGNORECASE,
)
_FTE = re.compile(r"\b(0?\.\d+|1(?:\.0)?)\s*FTE\b", re.IGNORECASE)
_DAYS = re.compile(r"\b([1-5])\s*days?\s*(?:per|a|/)\s*week", re.IGNORECASE)
_FULL_TIME_HOURS = re.compile(r"full[\s-]time\s+hours", re.IGNORECASE)
_YEARS_EXPERIENCE = re.compile(r"\b1\d\s*\+\s*(years|yrs)", re.IGNORECASE)


def _term_hit(terms: list[str], text: str) -> bool:
    return any(
        re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.IGNORECASE)
        for term in terms
    )


@dataclass
class ScoreResult:
    rule_score: int
    matched_skills: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def score_job(job: JobData, profile_skills: set[str], settings: AppSettings) -> ScoreResult:
    w = settings.weights
    text = job.text
    flags: list[str] = []

    if job.work_type in FLEXIBLE_WORK_TYPES:
        work_pts = w.flexible_work
        flags.append("flexible")
    else:
        work_pts = w.full_time

    matched = sorted(extract_skills(f"{job.title} {text}") & profile_skills)
    skill_pts = round(min(len(matched), w.skill_saturation) / w.skill_saturation * w.skill_max)

    if _term_hit(settings.role_penalty_terms, job.title) or _YEARS_EXPERIENCE.search(text):
        role_pts = 0
    elif _term_hit(settings.role_boost_terms, job.title):
        role_pts = w.role_max
    else:
        role_pts = w.role_max // 3

    weekly_hours = []
    for value, unit in _HOURS.findall(text):
        hours_value = float(value)
        if unit.lower() == "fortnight":
            hours_value /= 2
        weekly_hours.append(hours_value)
    fte_values = [float(v) for v in _FTE.findall(text)]
    day_values = [int(d) for d in _DAYS.findall(text)]

    if (
        (weekly_hours and max(weekly_hours) >= 24)
        or (fte_values and max(fte_values) >= 0.65)
        or (day_values and max(day_values) >= 4)
        or (job.work_type != "full_time" and _FULL_TIME_HOURS.search(text))
    ):
        flags.append("hours")

    return ScoreResult(
        rule_score=min(100, work_pts + skill_pts + role_pts), matched_skills=matched, flags=flags
    )


def blend(rule_score: int, llm_score: int | None) -> int:
    if llm_score is None:
        return rule_score
    return round(0.6 * rule_score + 0.4 * llm_score)
