import re
from dataclasses import dataclass, field

from seekhunter.domain import FLEXIBLE_WORK_TYPES, JobData
from seekhunter.settings_model import AppSettings
from seekhunter.skills import extract_skills

_HOURS = re.compile(r"(\d{2})\s*\+?\s*(?:hours|hrs)\s*(?:per|a|/|each)\s*week", re.IGNORECASE)
_FULL_TIME_HOURS = re.compile(r"full[\s-]time\s+hours", re.IGNORECASE)


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

    title = job.title.lower()
    lowered = text.lower()
    if any(t in title for t in settings.role_penalty_terms) or "10+ years" in lowered:
        role_pts = 0
    elif any(t in title for t in settings.role_boost_terms):
        role_pts = w.role_max
    else:
        role_pts = w.role_max // 3

    hours = [int(h) for h in _HOURS.findall(text)]
    if (hours and max(hours) >= 24) or (job.work_type != "full_time" and _FULL_TIME_HOURS.search(text)):
        flags.append("hours")

    return ScoreResult(
        rule_score=min(100, work_pts + skill_pts + role_pts), matched_skills=matched, flags=flags
    )


def blend(rule_score: int, llm_score: int | None) -> int:
    if llm_score is None:
        return rule_score
    return round(0.6 * rule_score + 0.4 * llm_score)
