import pytest

from seekhunter.resume_doc import Bullet, Experience, ResumeDoc, SkillLine
from seekhunter.tailor.headline import HEADLINE_MAX, fallback_headline, validate_headline


def _exp(eid, title):
    return Experience(id=eid, title=title, company=eid.title(), location="Taipei", dates="2020",
                      bullets=[Bullet(id=f"{eid}-b1", text="Built things with React.")])


BASE = ResumeDoc(
    summary="Senior Full-Stack Software Engineer with 6 years of experience building web apps and APIs.",
    skills=[SkillLine(id="languages", category="Languages", items=["TypeScript", "C#", "Java", "SQL"]),
            SkillLine(id="frontend", category="Frontend", items=["React", "Vue 3", "Next.js"]),
            SkillLine(id="backend", category="Backend", items=["Node.js", "Spring Boot", "Spring AI"]),
            SkillLine(id="data", category="Data", items=["PostgreSQL", "MySQL"])],
    experiences=[_exp("goldcrown", "Front-End Developer"), _exp("microsoft", "Software Engineer – VDI Team"),
                 _exp("sampras", "Senior Software Engineer")],
    projects=[],
)
TITLE = "Full Stack (Java) Developer"
AD = "Full stack Java developer. Spring Boot, React, Hibernate, PostgreSQL and relational databases."


def _check(raw, title=TITLE, ad=AD, supported=()):
    return validate_headline(raw, BASE, job_title=title, ad_text=ad, supported=list(supported))


@pytest.mark.parametrize("raw", [
    "Full Stack Software Engineer · Java, Spring Boot, React",
    "Senior Full-Stack Developer · Java, React, PostgreSQL",
    "Full Stack Java Developer | Spring Boot, React, Vue 3",
    "Software Engineer",
])
def test_valid_headline_kept(raw):
    headline, warning = _check(raw)
    assert headline == raw
    assert warning is None


def test_supported_phrase_allowed_in_tech_list():
    headline, warning = _check("Full Stack Developer · Java, Spring Boot, Relational Databases",
                               supported=["relational databases"])
    assert warning is None and headline.endswith("Relational Databases")


@pytest.mark.parametrize("raw,why", [
    ("Lead Software Engineer · Java, React", "Lead"),
    ("Principal Full Stack Developer · Java", "Principal"),
    ("Head of Engineering · Java", "Head"),
    ("Full Stack Developer · Java, Hibernate", "Hibernate"),
    ("Full Stack Developer · Java, Kubernetes", "Kubernetes"),
    ("Salesforce Developer · Java", "Salesforce"),
    ("Java, Spring Boot, React", "role"),
    ("Full Stack Developer · Java, React with 10 years", "10"),
    ("Full Stack Software Engineer · " + ", ".join(["Java", "Spring Boot", "React", "TypeScript", "Node.js",
                                                    "PostgreSQL", "MySQL", "Next.js"]), "long"),
])
def test_invalid_headline_falls_back(raw, why):
    headline, warning = _check(raw)
    assert headline == fallback_headline(BASE, job_title=TITLE, ad_text=AD)
    assert warning and "headline" in warning.lower()


def test_missing_headline_uses_fallback_without_warning():
    headline, warning = _check(None)
    assert headline == fallback_headline(BASE, job_title=TITLE, ad_text=AD)
    assert warning is None


def test_fallback_uses_cleaned_job_title_and_ad_techs():
    title = "Senior Full Stack (Java) Developer - 12 Month Contract"
    h = fallback_headline(BASE, job_title=title, ad_text=AD)
    assert h == "Full Stack Java Developer · Spring Boot, React, PostgreSQL"
    assert len(h) <= HEADLINE_MAX


def test_fallback_uses_first_past_title_when_job_title_does_not_fit():
    h = fallback_headline(BASE, job_title="Salesforce Consultant", ad_text="Apex, Java and React.")
    assert h == "Front-End Developer · Java, React"


def test_fallback_without_matching_techs_is_role_only():
    assert fallback_headline(BASE, job_title="Software Engineer", ad_text="Nothing technical.") == \
        "Software Engineer"


def test_fallback_is_valid():
    h = fallback_headline(BASE, job_title=TITLE, ad_text=AD)
    assert _check(h) == (h, None)
