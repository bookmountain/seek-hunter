"""The tailored resume's role headline ("Full Stack Software Engineer · Java, Spring Boot, React").

The LLM proposes one; `validate_headline` only accepts it when every word is backed by the resume:
role words come from the job title and/or the candidate's real titles/summary, seniority words must
appear in those titles/summary, and every listed technology is a resume skill (or a SUPPORTED target
phrase). Anything else falls back to `fallback_headline`, which is derived deterministically.
"""

import re

from seekhunter.resume_doc import ResumeDoc
from seekhunter.skills import SKILL_ALIASES, extract_skills
from seekhunter.tailor.phrases import ALIAS_RE, Evidence, is_supported, norm

HEADLINE_MAX = 90
FALLBACK_TECHS = 3
SEP = " · "

ROLE_NOUNS = frozenset({"engineer", "developer", "programmer", "technician", "analyst", "specialist"})
ROLE_WORDS = frozenset("""software full stack front back end frontend backend web ai ml platform cloud data qa
test testing support it mobile application applications systems devops integration solutions and &
""".split())
SENIORITY = frozenset({"senior", "sr", "lead", "principal", "head", "staff", "chief", "director", "manager",
                       "architect", "junior", "jr", "graduate", "intern", "mid", "level", "associate"})
_NOISE = re.compile(
    r"\b(contract|contractor|temp|temporary|permanent|perm|full[\s-]?time|part[\s-]?time|casual|fixed[\s-]?term|"
    r"\d+\s*(months?|mths?|weeks?)|months?|maternity|parental|leave|cover|remote|hybrid|onsite|"
    r"immediate start|urgent|initial)\b", re.IGNORECASE)
_ROLE_SPLIT = re.compile(r"\s*(?:·|\||—|–|:|\s-\s)\s*")
_TECH_SPLIT = re.compile(r"\s*(?:,|·|\|)\s*")


def numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d+(?:[.,]\d+)*", text)}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9#+&]+", text)


class _Context:
    def __init__(self, base: ResumeDoc, job_title: str, supported: list[str]):
        self.base = base
        self.ev = Evidence(base)
        self.roles = set(_tokens(self.ev.roles))
        self.title = set(_tokens(norm(job_title)))
        self.items = {i.casefold() for line in base.skills for i in line.items}
        self.supported = {s.casefold() for s in supported}
        self.numbers = numbers(base.corpus())

    def role_ok(self, role: str) -> bool:
        text = norm(role.replace("(", " ").replace(")", " "))
        if not text or not extract_skills(role) <= self.ev.skills:
            return False
        words = _tokens(ALIAS_RE.sub(" ", text))
        if not any(w in ROLE_NOUNS for w in words):
            return False
        for w in words:
            if w in SENIORITY:
                if w not in self.roles:
                    return False
            elif w in ROLE_NOUNS:
                if w not in self.roles and w not in self.title:
                    return False
            elif w in ROLE_WORDS:
                if w not in self.roles and not (w in self.title and re.search(rf"\b{re.escape(w)}\b",
                                                                              self.ev.text)):
                    return False
            else:
                return False
        return True

    def tech_ok(self, tech: str) -> bool:
        key = " ".join(tech.split()).casefold()
        if not key:
            return False
        if key in self.items:
            return True
        if not is_supported(tech, self.ev):
            return False
        return bool(extract_skills(tech)) or key in self.supported


def _split(headline: str) -> tuple[str, list[str]]:
    parts = _ROLE_SPLIT.split(headline, maxsplit=1)
    role = parts[0]
    techs = _TECH_SPLIT.split(parts[1]) if len(parts) > 1 else []
    return role, [t for t in techs if t]


def _problem(headline: str, ctx: _Context) -> str | None:
    if len(headline) > HEADLINE_MAX:
        return f"too long ({len(headline)} chars)"
    if new := numbers(headline) - ctx.numbers:
        return f"adds {', '.join(sorted(new))}"
    role, techs = _split(headline)
    if "," in role or not ctx.role_ok(role):
        return f"role '{role}' isn't backed by your titles or summary"
    bad = [t for t in techs if not ctx.tech_ok(t)]
    if bad:
        return f"lists {', '.join(bad)} (not in your resume)"
    return None


def _clean_title(job_title: str) -> str:
    text = re.split(r"\s+[-–—|]\s+|,|/(?=\s)", job_title, maxsplit=1)[0]
    text = _NOISE.sub(" ", text.replace("(", " ").replace(")", " "))
    words = [w for w in text.split() if w.casefold().strip(".") not in SENIORITY]
    return " ".join(words)


def _first_title(base: ResumeDoc) -> str:
    for exp in base.experiences:
        role = re.split(r"\s+[-–—|]\s+|,", exp.title, maxsplit=1)[0].strip()
        if role:
            return role
    return "Software Engineer"


def _ad_position(item: str, ad: str) -> tuple[int, int] | None:
    """(position, 0 if the item itself is in the ad else 1 for a vocabulary alias), or None."""
    pattern = r"(?<![A-Za-z0-9_.#+])" + re.escape(item) + r"(?![A-Za-z0-9_#+])"
    if m := re.search(pattern, ad, re.IGNORECASE):
        return m.start(), 0
    canon = extract_skills(item)
    if canon and canon <= extract_skills(ad):
        hits = [m.start() for name in canon for a in SKILL_ALIASES[name]
                if (m := re.search(r"(?<![A-Za-z0-9_.#+])" + re.escape(a) + r"(?![A-Za-z0-9_#+])", ad,
                                   re.IGNORECASE))]
        if hits:
            return min(hits), 1
    return None


def _fallback_techs(base: ResumeDoc, ad_text: str, role: str) -> list[str]:
    taken = extract_skills(role)
    found = []
    for line in base.skills:
        for item in line.items:
            pos = _ad_position(item, ad_text)
            if pos is not None:
                found.append((pos, item))
    techs = []
    for _, item in sorted(found, key=lambda f: f[0]):
        canon = extract_skills(item) or {item.casefold()}
        if canon & taken:
            continue
        taken |= canon
        techs.append(item)
        if len(techs) == FALLBACK_TECHS:
            break
    return techs


def fallback_headline(base: ResumeDoc, *, job_title: str, ad_text: str) -> str:
    """Role = the job title without seniority/contract noise when it fits the candidate's real titles
    (shares a role noun with one), else the most recent title; techs = up to three resume skills the ad
    mentions, in ad order."""
    ctx = _Context(base, job_title, [])
    role = _clean_title(job_title)
    title_nouns = {w for e in base.experiences for w in _tokens(norm(e.title)) if w in ROLE_NOUNS}
    if not (role and ctx.role_ok(role) and set(_tokens(norm(role))) & title_nouns):
        role = _first_title(base)
    techs = _fallback_techs(base, ad_text, role)
    while techs and len(role + SEP + ", ".join(techs)) > HEADLINE_MAX:
        techs.pop()
    return role + SEP + ", ".join(techs) if techs else role


def validate_headline(raw: str | None, base: ResumeDoc, *, job_title: str, ad_text: str,
                      supported: list[str] | None = None) -> tuple[str, str | None]:
    """(headline to use, warning or None). A missing headline silently uses the fallback."""
    fallback = fallback_headline(base, job_title=job_title, ad_text=ad_text)
    headline = " ".join((raw or "").split())
    if not headline:
        return fallback, None
    problem = _problem(headline, _Context(base, job_title, supported or []))
    if problem:
        return fallback, f"Headline '{headline[:100]}' {problem}; used '{fallback}' instead."
    return headline, None
