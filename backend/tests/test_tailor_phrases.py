from seekhunter.resume_doc import Bullet, Experience, ResumeDoc, SkillLine
from seekhunter.tailor import phrases


def _doc(summary="Senior Full-Stack Software Engineer building web apps with React and Java.",
         bullets=("Built REST-free GraphQL services with NestJS.",), skills=None) -> ResumeDoc:
    return ResumeDoc(
        summary=summary,
        skills=skills or [SkillLine(id="data", category="Data", items=["PostgreSQL", "MySQL", "Redis"]),
                          SkillLine(id="tools", category="Tools",
                                    items=["Jest", "GitHub Actions", "Selenium"])],
        experiences=[Experience(id="ms", title="Front-End Developer", company="Microsoft", location="Taipei",
                                dates="2022", bullets=[Bullet(id=f"ms-b{i}", text=t)
                                                       for i, t in enumerate(bullets, 1)])],
        projects=[])


def test_relational_databases_supported_by_postgresql():
    assert phrases.is_supported("relational databases", _doc())
    assert phrases.is_supported("Relational Database", _doc())
    assert phrases.is_supported("SQL", _doc())  # PostgreSQL / MySQL imply SQL


def test_relational_databases_unsupported_without_sql_evidence():
    doc = _doc(skills=[SkillLine(id="data", category="Data", items=["MongoDB"])])
    assert not phrases.is_supported("relational databases", doc)


def test_hibernate_and_bootstrap_unsupported():
    doc = _doc()
    assert not phrases.is_supported("Hibernate", doc)
    assert not phrases.is_supported("Bootstrap", doc)
    assert not phrases.is_supported("JIRA", doc)


def test_agile_unsupported_unless_mentioned():
    assert not phrases.is_supported("Agile development", _doc())
    assert not phrases.is_supported("Scrum", _doc())
    doc = _doc(bullets=("Shipped features in two-week sprints with the product team.",))
    assert phrases.is_supported("Agile development", doc)
    assert phrases.is_supported("agile", doc)


def test_full_stack_from_summary_and_literal_terms():
    doc = _doc()
    assert phrases.is_supported("full stack", doc)
    assert phrases.is_supported("Full-Stack Development", doc)
    assert phrases.is_supported("React", doc)
    assert not phrases.is_supported("full stack", _doc(summary="Front-end engineer."))


def test_skill_vocabulary_aliases_and_testing():
    doc = _doc()
    assert phrases.is_supported("CI/CD", doc)  # GitHub Actions
    assert phrases.is_supported("unit testing", doc)  # Jest
    assert phrases.is_supported("test automation", doc)  # Selenium
    assert not phrases.is_supported("Kubernetes", doc)
    assert phrases.is_supported("software development best practices", doc)  # tests + CI/CD


def test_annotate_splits_supported_and_unsupported_preserving_order():
    sup, unsup = phrases.annotate(["Hibernate", "relational databases", "Java", "relational databases",
                                   "Agile"], _doc())
    assert sup == ["relational databases", "Java"]
    assert unsup == ["Hibernate", "Agile"]


def test_job_phrases_extracts_skills_and_ats_phrases():
    ad = ("We need a Full-Stack Java developer: Spring Boot, React, Hibernate, relational databases, "
          "REST APIs, CI/CD pipelines, Agile/Scrum team, strong problem-solving and unit testing.")
    found = phrases.job_phrases(ad)
    for want in ("Java", "Spring Boot", "React", "REST APIs", "CI/CD", "relational databases", "full stack",
                 "agile", "scrum", "problem-solving", "unit testing"):
        assert want in found, want
    assert len(found) == len({f.casefold() for f in found})


def test_rm_phrases_from_previous_result():
    result = {"resume_matcher": {"job_keywords": {"required_skills": ["Java", "Hibernate"],
                                                  "preferred_skills": ["Bootstrap"],
                                                  "keywords": ["relational databases", "Java"]},
                                 "missing_keywords": ["JIRA"], "matched_keywords": ["React"]}}
    assert phrases.rm_phrases(result) == ["Java", "Hibernate", "Bootstrap", "relational databases", "JIRA",
                                          "React"]
    assert phrases.rm_phrases({}) == []
    assert phrases.rm_phrases({"resume_matcher": {"status": "failed"}}) == []


def test_concept_plus_unbacked_word_is_unsupported():
    doc = _doc(bullets=("Delivered projects for clients in retail.",))
    assert phrases.is_supported("stakeholders", doc)
    assert not phrases.is_supported("stakeholder communication", doc)
    assert not phrases.is_supported("Java and Hibernate", doc)
    assert phrases.is_supported("Java development", doc)
