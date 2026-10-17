"""Deterministic ATS score for a SeekHunter `ResumeDoc`, using Resume-Matcher's formula.

Vendored and adapted from Resume-Matcher (https://github.com/srbhr/Resume-Matcher),
`apps/backend/app/services/ats.py` and `services/refiner.py` (keyword matching).
Copyright Saurabh Rai and Resume-Matcher contributors. Licensed under the Apache License,
Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0). Changes from the original: only the
scoring pieces are kept (no recommendations / injectable-keyword analysis), the input is built from
SeekHunter's `ResumeDoc` via `resume_to_rm` (a tailored resume's headline is RM's
`personalInfo.title`), and `title_match` is reported as `title_alignment`.

Weights: keyword match 40%, skills coverage 20%, title alignment 15%, section completeness 15%,
date consistency 10%. A component that cannot be scored (no job title, fewer than two dates) is
None and its weight is redistributed across the others, exactly as in Resume-Matcher.
"""

import re
from pathlib import Path
from typing import Any

from seekhunter.resume_doc import ResumeDoc, macro_args, tex_to_text

WEIGHTS: dict[str, float] = {
    "keyword_match": 0.40,
    "skills_coverage": 0.20,
    "title_match": 0.15,
    "section_completeness": 0.15,
    "date_consistency": 0.10,
}
BREAKDOWN_NAMES = {"title_match": "title_alignment"}
MISSING_LIMIT = 15

_SECTION_COUNT = 4  # summary, experience, education, skills
_TITLE_IN_HEADLINE = 100.0
_TITLE_IN_SUMMARY = 75.0
_TITLE_OVERLAP_MAX = 50.0
_TITLE_STOPWORDS = frozenset({"a", "an", "and", "the", "of", "for", "in", "to", "at", "&"})

_YEAR = r"(?:19|20)\d{2}"
_MONTH = (
    r"(?i:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DATE_PATTERN = re.compile(
    rf"(?P<iso>\b{_YEAR}[-/]\d{{1,2}}\b)"
    rf"|(?P<numeric>\b\d{{1,2}}[/.-]{_YEAR}\b)"
    rf"|(?P<name_year>\b{_MONTH}\.?,?\s+{_YEAR}\b)"
    rf"|(?P<name_short_year>\b{_MONTH}\.?\s+'\d{{2}}\b)"
    rf"|(?P<year>\b{_YEAR}\b)"
)
_MIN_DATES_FOR_CONSISTENCY = 2

_CJK_CHAR_CLASS = (
    r"[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u31f0-\u31ff"
    r"\u3400-\u9fff\ua960-\ua97f\uac00-\ud7ff\uf900-\ufaff"
    r"\uff66-\uffdc\U0001b000-\U0001b16f\U00020000-\U0003ffff]"
)
_CJK_RE = re.compile(_CJK_CHAR_CLASS)


# --------------------------------------------------------------------------- ResumeDoc -> RM shape

def _plain(text: str) -> str:
    """Drop SeekHunter's inline markup (`[label](url)`, `**bold**`) so only visible text is scored."""
    text = re.sub(r"\[([^\]\n]+)\]\([^)\s]+\)", r"\1", text)
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


def _education(education_tex: str) -> list[dict[str, Any]]:
    entries = [{"degree": tex_to_text(a[0]), "years": tex_to_text(a[1]), "institution": tex_to_text(a[2]),
                "description": tex_to_text(a[3]) if len(a) > 3 else None}
               for a in macro_args(education_tex, "resumeEducation", 4) if len(a) >= 3]
    if entries:
        return entries
    text = tex_to_text(education_tex)
    return [{"degree": "", "years": "", "institution": text, "description": None}] if text else []


def resume_to_rm(doc: ResumeDoc, contact: dict[str, str] | None = None) -> dict[str, Any]:
    """Resume-Matcher's `ResumeData` dict shape for a SeekHunter resume."""
    contact = contact or {}
    return {
        "personalInfo": {"name": contact.get("name", ""), "title": doc.headline or "",
                         "email": contact.get("email", ""),
                         "phone": contact.get("phone", "")},
        "summary": _plain(doc.summary),
        "workExperience": [{"title": e.title, "company": e.company, "location": e.location, "years": e.dates,
                            "description": [_plain(b.text) for b in e.bullets]} for e in doc.experiences],
        "education": _education(doc.education_tex),
        "personalProjects": [{"name": p.name, "role": p.stack, "years": "",
                              "description": [_plain(b.text) for b in p.bullets]} for p in doc.projects],
        "additional": {"technicalSkills": [_plain(i) for s in doc.skills for i in s.items]},
    }


def contact_from_latex(latex_dir: Path) -> dict[str, str]:
    """Email / phone from the resume header (`\\href{mailto:..}`, `\\href{tel:..}`); {} if unreadable."""
    try:
        tex = (latex_dir / "resume.tex").read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, str] = {}
    if m := re.search(r"\\href\{mailto:([^}]+)\}", tex):
        out["email"] = m.group(1).strip()
    if m := re.search(r"\\href\{tel:([^}]+)\}", tex):
        out["phone"] = m.group(1).strip()
    return out


def seekhunter_keywords(title: str, matched: list[str], gaps: list[str]) -> dict[str, Any]:
    """Job keywords in Resume-Matcher's shape, from SeekHunter's own analysis of the ad."""
    terms = list(dict.fromkeys([*matched, *gaps]))
    return {"role": title, "required_skills": terms, "preferred_skills": [], "keywords": terms}


# --------------------------------------------------------------------------- vendored scoring

def _extract_all_text(data: Any) -> str:
    parts: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)

    _walk(data)
    return " ".join(parts)


def _keyword_in_text(keyword: str, text: str) -> bool:
    """Whole-word (CJK-aware) match, as in Resume-Matcher's refiner: 'java' never matches 'javascript'."""
    normalized_keyword = keyword.strip().lower()
    if not normalized_keyword:
        return False
    normalized_text = text.lower()
    if _CJK_RE.search(normalized_keyword):
        return normalized_keyword in normalized_text
    escaped = re.escape(normalized_keyword)
    pattern = rf"(?:(?<!\w)|(?<={_CJK_CHAR_CLASS})){escaped}(?:(?!\w)|(?={_CJK_CHAR_CLASS}))"
    return bool(re.search(pattern, normalized_text))


def job_keyword_terms(job_keywords: dict[str, Any]) -> list[str]:
    terms: dict[str, None] = {}
    for field in ("required_skills", "preferred_skills", "keywords"):
        for term in job_keywords.get(field) or []:
            if isinstance(term, str) and term.strip():
                terms.setdefault(term, None)
    return list(terms)


def _keyword_match(resume: dict[str, Any], job_keywords: dict[str, Any]) -> float:
    terms = job_keyword_terms(job_keywords)
    if not terms:
        return 0.0
    text = _extract_all_text(resume)
    return sum(1 for kw in terms if _keyword_in_text(kw, text)) / len(terms) * 100


def _skills_coverage(resume: dict[str, Any], job_keywords: dict[str, Any]) -> float:
    jd_skills = [*(job_keywords.get("required_skills") or []), *(job_keywords.get("preferred_skills") or [])]
    if not jd_skills:
        return 0.0
    resume_skills = {s.lower() for s in (resume.get("additional") or {}).get("technicalSkills") or []
                     if isinstance(s, str)}
    text = _extract_all_text(resume).lower()
    matched = sum(1 for s in jd_skills
                  if isinstance(s, str) and (s.lower() in resume_skills or _keyword_in_text(s, text)))
    return min(100.0, matched / len(jd_skills) * 100)


def _title_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[^\W_]+", text.lower()) if t not in _TITLE_STOPWORDS}


def _title_match(resume: dict[str, Any], job_keywords: dict[str, Any]) -> float | None:
    role = job_keywords.get("role")
    if not isinstance(role, str) or not role.strip():
        return None
    headline = str((resume.get("personalInfo") or {}).get("title") or "")
    summary = str(resume.get("summary") or "")
    if _keyword_in_text(role, headline):
        return _TITLE_IN_HEADLINE
    if _keyword_in_text(role, summary):
        return _TITLE_IN_SUMMARY
    role_tokens = _title_tokens(role)
    if not role_tokens:
        return 0.0
    return round(len(role_tokens & _title_tokens(headline)) / len(role_tokens) * _TITLE_OVERLAP_MAX, 1)


def _date_consistency(resume: dict[str, Any]) -> float | None:
    style_counts: dict[str, int] = {}
    for key in ("workExperience", "education", "personalProjects"):
        for entry in resume.get(key) or []:
            years = entry.get("years") if isinstance(entry, dict) else None
            if not isinstance(years, str):
                continue
            for match in _DATE_PATTERN.finditer(years):
                if match.lastgroup:
                    style_counts[match.lastgroup] = style_counts.get(match.lastgroup, 0) + 1
    total = sum(style_counts.values())
    if total < _MIN_DATES_FOR_CONSISTENCY:
        return None
    return round(max(style_counts.values()) / total * 100, 1)


def _section_completeness(resume: dict[str, Any]) -> float:
    info = resume.get("personalInfo") or {}
    has_contact = bool(info.get("email") or info.get("phone"))
    skills = (resume.get("additional") or {}).get("technicalSkills")
    found = sum([bool(resume.get("summary")), bool(resume.get("workExperience")),
                 bool(resume.get("education")), bool(skills)])
    return (found + has_contact) / (_SECTION_COUNT + 1) * 100


def score_resume(resume: dict[str, Any], job_keywords: dict[str, Any]) -> dict[str, Any]:
    """`{score, breakdown{keyword_match, skills_coverage, title_alignment, section_completeness,
    date_consistency}, missing_keywords, matched_keywords}` for an RM-shaped resume dict."""
    sub: dict[str, float | None] = {
        "keyword_match": min(100.0, max(0.0, _keyword_match(resume, job_keywords))),
        "skills_coverage": _skills_coverage(resume, job_keywords),
        "title_match": _title_match(resume, job_keywords),
        "section_completeness": _section_completeness(resume),
        "date_consistency": _date_consistency(resume),
    }
    scored = {k: v for k, v in sub.items() if v is not None}
    total_weight = sum(WEIGHTS[k] for k in scored)
    overall = sum(v * WEIGHTS[k] for k, v in scored.items()) / total_weight if total_weight else 0.0
    text = _extract_all_text(resume)
    terms = job_keyword_terms(job_keywords)
    return {
        "score": round(overall, 1),
        "breakdown": {BREAKDOWN_NAMES.get(k, k): (round(v, 1) if v is not None else None)
                      for k, v in sub.items()},
        "missing_keywords": [t for t in terms if not _keyword_in_text(t, text)][:MISSING_LIMIT],
        "matched_keywords": [t for t in terms if _keyword_in_text(t, text)],
    }


def score_doc(doc: ResumeDoc, job_keywords: dict[str, Any], contact: dict[str, str] | None = None) -> dict:
    return score_resume(resume_to_rm(doc, contact), job_keywords)
