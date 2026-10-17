"""Job phrasing the tailored resume may use, and whether the resume actually backs it up.

`job_phrases` pulls ATS-style terms out of an ad deterministically (skills vocabulary + a short list of
common ATS phrases); `rm_phrases` reuses Resume-Matcher's keyword list from an earlier run on the same
job. `annotate` splits them into SUPPORTED (evidence in the resume: the phrase itself, a synonym, or a
clear superset such as PostgreSQL -> "relational databases") and UNSUPPORTED (gaps; never added).
"""

import re
from collections.abc import Callable, Iterable

from seekhunter.resume_doc import ResumeDoc, tex_to_text
from seekhunter.skills import SKILL_ALIASES, extract_skills

PHRASE_MAX_LEN = 40
TARGET_LIMIT = 40

# display text -> pattern on the (lower-cased) ad
ATS_PHRASES: list[tuple[str, str]] = [
    ("relational databases", r"relational databases?|\brdbms\b"),
    ("full stack", r"\bfull[\s-]?stack\b"),
    ("agile", r"\bagile\b"),
    ("scrum", r"\bscrum\b"),
    ("unit testing", r"\bunit[\s-]?test"),
    ("test automation", r"\btest automation\b|\bautomated test"),
    ("cloud", r"\bcloud\b"),
    ("stakeholders", r"\bstakeholders?\b"),
    ("problem-solving", r"\bproblem[\s-]?solving\b"),
    ("best practices", r"\bbest practices\b"),
    ("object-oriented", r"\bobject[\s-]?oriented\b|\boop\b"),
]
_ATS_RE = [(name, re.compile(p, re.IGNORECASE)) for name, p in ATS_PHRASES]

# Words that don't change what a phrase claims ("Java development" claims no more than "Java").
_GENERIC = frozenset("""and or with in of the a an for using experience development developing developer
engineering programming language languages framework frameworks skills skill knowledge proficiency
strong solid working hands on based applications application apps app services tools tooling
database databases methodology methodologies environment environments""".split())


def norm(text: str) -> str:
    text = text.casefold().replace(" ", " ")
    text = re.sub(r"\b(front|back|full)[\s-]?(end|stack)\b", r"\1 \2", text)
    text = re.sub(r"(?<=\w)-(?=\w)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class Evidence:
    """Searchable view of one resume: normalised text, roles text and skills vocabulary hits."""

    def __init__(self, doc: ResumeDoc):
        raw = doc.corpus() + "\n" + tex_to_text(doc.education_tex)
        self.text = norm(raw)
        self.roles = norm(" ".join([doc.summary, *(e.title for e in doc.experiences)]))
        self.skills = extract_skills(raw) | {s for line in doc.skills for i in line.items
                                             for s in extract_skills(i)}

    def has(self, pattern: str) -> bool:
        return re.search(pattern, self.text) is not None

    def any_skill(self, *names: str) -> bool:
        return bool(self.skills.intersection(names))

    def testing(self) -> bool:
        return self.any_skill("Jest", "Playwright", "Selenium") or self.has(
            r"\bunit tests?\b|\bunit testing\b|\bjunit\b|\bpytest\b|\bvitest\b|\btesting library\b|"
            r"\bxunit\b|\bnunit\b|\bautomated tests?\b|\btest coverage\b|\bcoverage\b")


# (pattern on the normalised phrase, evidence check). Every concept a phrase mentions must be backed.
_CONCEPTS: list[tuple[re.Pattern[str], Callable[[Evidence], bool]]] = [
    (re.compile(p), f) for p, f in [
        (r"\brelational\b|\brdbms\b|^sql$|\bsql databases?\b",
         lambda e: e.any_skill("SQL", "PostgreSQL", "MySQL", "SQL Server")),
        (r"\bfull stack\b", lambda e: "full stack" in e.text),
        (r"\bscrum\b", lambda e: e.has(r"\bscrum\b")),
        (r"\bagile\b|\bkanban\b|\bsprints?\b",
         lambda e: e.has(r"\bagile\b|\bscrum\b|\bsprints?\b|\bkanban\b")),
        (r"\bunit test", lambda e: e.testing()),
        (r"\btest automation\b|\bautomated test",
         lambda e: e.any_skill("Selenium", "Playwright") or e.has(r"\bautomated tests?\b|\bcypress\b")),
        (r"\bcloud\b", lambda e: e.any_skill("Azure", "AWS", "GCP", "Cloudflare") or e.has(r"\bcloud\b")),
        (r"\bbest practices?\b",
         lambda e: sum([e.testing(), e.any_skill("CI/CD"), e.has(r"\bcode reviews?\b")]) >= 2),
        (r"\bproblem solving\b",
         lambda e: e.has(r"troubleshoot|debug|diagnos|\bresolv|problem solving|root cause")),
        (r"\bstakeholders?\b",
         lambda e: e.has(r"\bstakeholders?\b|\bclients?\b|\bcustomers?\b|\bproduct (owner|manager)s?\b")),
        (r"\bobject oriented\b|\boop\b",
         lambda e: e.any_skill("Java", "C#", "C++", "Kotlin", "TypeScript", "Python")),
        (r"\b(software|web) (development|engineering)\b", lambda e: e.has(r"\b(engineer|developer)s?\b")),
    ]
]

ALIAS_RE = re.compile("|".join(
    r"(?<![a-z0-9_.#+])" + re.escape(norm(a)) + r"(?![a-z0-9_#+])"
    for a in sorted({a for aliases in SKILL_ALIASES.values() for a in aliases}, key=len, reverse=True)))


def _literal(phrase: str, ev: Evidence) -> bool:
    p = re.escape(phrase)
    if phrase.endswith("s"):
        p = re.escape(phrase[:-1]) + "s?"
    else:
        p += "s?"
    return re.search(r"(?<![a-z0-9_.#+])" + p + r"(?![a-z0-9_#+])", ev.text) is not None


def mentions(phrase: str, text: str) -> bool:
    """Whole-word, hyphen/case-insensitive: does `text` mention `phrase`?"""
    p = norm(phrase)
    pattern = r"(?<![a-z0-9_.#+])" + re.escape(p) + r"(?![a-z0-9_#+])"
    return bool(p) and re.search(pattern, norm(text)) is not None


def is_supported(phrase: str, doc: ResumeDoc | Evidence) -> bool:
    """True when the resume backs `phrase` (literally, via a synonym, or a clear superset)."""
    ev = doc if isinstance(doc, Evidence) else Evidence(doc)
    text = norm(phrase)
    if not text:
        return False
    concepts = [(pattern, check) for pattern, check in _CONCEPTS if pattern.search(text)]
    if not concepts and _literal(text, ev):
        return True
    rest = text
    for pattern, _ in concepts:
        rest = re.sub(f"(?:{pattern.pattern})\\w*", " ", rest)  # "unit test" also takes "-ing"
    skills = extract_skills(rest)
    if not (concepts or skills) or not skills <= ev.skills or not all(check(ev) for _, check in concepts):
        return False
    rest = ALIAS_RE.sub(" ", rest)
    # every word must be covered by a backed concept, a resume skill, or be filler ("stakeholder
    # communication" claims more than "clients" shows)
    return all(w in _GENERIC for w in re.findall(r"[a-z0-9#+]+", rest))


def _dedupe(values: Iterable[str]) -> list[str]:
    seen, out = set(), []
    for v in values:
        v = " ".join(str(v).split())
        if v and len(v) <= PHRASE_MAX_LEN and v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)
    return out


def annotate(phrases: Iterable[str], doc: ResumeDoc) -> tuple[list[str], list[str]]:
    """(supported, unsupported), each deduplicated, in input order."""
    ev = Evidence(doc)
    supported, unsupported = [], []
    for p in _dedupe(phrases)[:TARGET_LIMIT]:
        (supported if is_supported(p, ev) else unsupported).append(p)
    return supported, unsupported


def job_phrases(ad_text: str) -> list[str]:
    """Skills-vocabulary terms (in the ad's own wording, e.g. "Spring Boot") and common ATS phrases in
    the ad, in order of first appearance."""
    hits: list[tuple[int, str]] = []
    for name, aliases in SKILL_ALIASES.items():
        found = [m for a in [name, *aliases]
                 if (m := re.search(r"(?<![A-Za-z0-9_.#+])" + re.escape(a) + r"(?![A-Za-z0-9_#+])",
                                    ad_text, re.IGNORECASE))]
        if found:
            first = min(found, key=lambda m: (m.start(), -len(m.group(0))))
            hits.append((first.start(), first.group(0)))
    for name, pattern in _ATS_RE:
        if m := pattern.search(ad_text):
            hits.append((m.start(), name))
    return _dedupe(name for _, name in sorted(hits, key=lambda h: h[0]))


def rm_phrases(result: dict | None) -> list[str]:
    """Resume-Matcher's keywords for the job from a previous tailoring's `result` ([] if none)."""
    rm = (result or {}).get("resume_matcher") or {}
    kw = rm.get("job_keywords") or {}
    values = [*(kw.get("required_skills") or []), *(kw.get("preferred_skills") or []),
              *(kw.get("keywords") or []), *(rm.get("missing_keywords") or []),
              *(rm.get("matched_keywords") or [])]
    return _dedupe(v for v in values if isinstance(v, str))
