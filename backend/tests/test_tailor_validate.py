import pytest

from seekhunter.resume_doc import Bullet, Experience, Project, ResumeDoc, SkillLine
from seekhunter.tailor.models import TailorOutput
from seekhunter.tailor.validate import validate


def _exp(eid: str, *texts: str) -> Experience:
    return Experience(id=eid, title=f"{eid} dev", company=eid.title(), location="Adelaide", dates="2020",
                      bullets=[Bullet(id=f"{eid}-b{i}", text=t) for i, t in enumerate(texts, start=1)])


BASE = ResumeDoc(
    summary="Full-stack engineer with 6 years of experience in React and TypeScript.",
    skills=[SkillLine(id="languages", category="Languages", items=["TypeScript", "C#", "Java", "Python"]),
            SkillLine(id="data", category="Data", items=["PostgreSQL", "Redis"])],
    experiences=[
        _exp("sampras", "Delivered 9 projects with NestJS and React.", "Cut latency by 97% on 6 endpoints.",
             "Rebuilt the waiting room on Cloudflare Workers."),
        _exp("microsoft", "Built labeling UI with React and Redux.", "Kept coverage above 90% with Jest.",
             "Built accessibility features."),
        _exp("kozyguru", "Built the property platform."),
    ],
    projects=[
        Project(id="auction", name="Auction", stack="RabbitMQ", bullets=[Bullet(id="auction-b1", text="x")]),
        Project(id="agent", name="Agent", stack="Spring AI", bullets=[Bullet(id="agent-b1", text="y")])],
)

LETTER = {"greeting": "Dear Brayden,", "paragraphs": ["one", "two", "three"], "sign_off": "Kind regards,"}


def _run(contact_name=None, **fields):
    data = {"summary": BASE.summary, "cover_letter": LETTER, **fields}
    return validate(BASE, TailorOutput.model_validate(data), contact_name=contact_name)


def test_noop_output_keeps_everything():
    res = _run()
    assert res.doc.experiences == BASE.experiences
    assert res.doc.skills == BASE.skills
    assert [p.id for p in res.doc.projects] == ["auction", "agent"]


def test_skill_reorder_trim_and_added_skill_rejected():
    res = _run(skills=[{"id": "languages", "items": ["java", "Kotlin", "TypeScript", "Java"]}])
    langs = res.doc.skills[0]
    assert langs.items == ["Java", "TypeScript"]  # original spelling, deduped, Kotlin dropped
    assert any("Kotlin" in w for w in res.warnings)
    assert res.doc.skills[1].items == ["PostgreSQL", "Redis"]  # untouched line kept


def test_skill_lines_reordered_and_unknown_line_ignored():
    res = _run(skills=[{"id": "data", "items": ["Redis"]}, {"id": "nope", "items": ["Go"]}])
    assert [s.id for s in res.doc.skills] == ["data", "languages"]
    assert res.doc.skills[0].items == ["Redis"]
    assert any("nope" in w for w in res.warnings)


def test_empty_skill_line_keeps_original():
    res = _run(skills=[{"id": "data", "items": []}])
    assert next(s for s in res.doc.skills if s.id == "data").items == ["PostgreSQL", "Redis"]


def test_reworded_bullet_with_new_number_reverts():
    res = _run(experiences=[{"id": "sampras", "bullets": [
        {"id": "sampras-b2", "text": "Cut API latency by 99% across 6 endpoints."},
        {"id": "sampras-b1", "text": "Shipped 9 client projects using NestJS and React."}]}])
    bullets = res.doc.experience("sampras").bullets
    assert [b.id for b in bullets] == ["sampras-b2", "sampras-b1"]
    assert bullets[0].text == "Cut latency by 97% on 6 endpoints."  # reverted
    assert bullets[1].text == "Shipped 9 client projects using NestJS and React."
    assert any("99" in w for w in res.warnings)


def test_reworded_bullet_with_unknown_tech_reverts():
    res = _run(experiences=[{"id": "microsoft", "bullets": [
        {"id": "microsoft-b1", "text": "Built labeling UI with React, Redux and Kubernetes."},
        {"id": "microsoft-b2", "text": "Kept coverage above 90% with Jest and Python tests."}]}])
    bullets = res.doc.experience("microsoft").bullets
    assert bullets[0].text == "Built labeling UI with React and Redux."
    assert any("Kubernetes" in w for w in res.warnings)
    # Python is elsewhere in the resume (skills), so it is allowed
    assert bullets[1].text == "Kept coverage above 90% with Jest and Python tests."


def test_unknown_and_duplicate_bullet_ids_dropped():
    res = _run(experiences=[{"id": "sampras", "bullets": [
        {"id": "sampras-b1", "text": "a"}, {"id": "sampras-b1", "text": "b"},
        {"id": "sampras-b9", "text": "c"},
        {"id": "microsoft-b1", "text": "d"}, {"id": "sampras-b3", "text": "e"}]}])
    assert [b.id for b in res.doc.experience("sampras").bullets] == ["sampras-b1", "sampras-b3"]
    assert any("sampras-b9" in w for w in res.warnings)


def test_roles_never_dropped_or_reordered():
    res = _run(experiences=[{"id": "kozyguru", "bullets": []}, {"id": "ghost", "bullets": []}])
    assert [e.id for e in res.doc.experiences] == ["sampras", "microsoft", "kozyguru"]
    assert res.doc.experience("kozyguru").bullets == BASE.experience("kozyguru").bullets
    assert any("ghost" in w for w in res.warnings)


def test_two_most_recent_roles_keep_at_least_two_bullets():
    res = _run(experiences=[
        {"id": "microsoft", "bullets": [{"id": "microsoft-b3", "text": "Built accessibility."}]},
        {"id": "kozyguru", "bullets": [{"id": "kozyguru-b1", "text": "Built it."}]}])
    assert [b.id for b in res.doc.experience("microsoft").bullets] == ["microsoft-b1", "microsoft-b3"]
    assert any("Microsoft" in w and "restored" in w for w in res.warnings)


def test_summary_with_unknown_skill_or_number_reverts():
    res = _run(summary="Engineer with 6 years in React and Kubernetes.")
    assert res.doc.summary == BASE.summary
    res = _run(summary="Engineer with 12 years in React.")
    assert res.doc.summary == BASE.summary
    res = _run(summary="Engineer with 6 years building React and TypeScript apps; 97% faster APIs.")
    assert res.doc.summary.startswith("Engineer with 6 years")


def test_summary_too_long_reverts():
    res = _run(summary="React " * 120)
    assert res.doc.summary == BASE.summary
    assert any("long" in w for w in res.warnings)


def test_projects_filtered_and_unknown_dropped():
    res = _run(projects=["agent", "ghost", "agent"])
    assert [p.id for p in res.doc.projects] == ["agent"]
    assert any("ghost" in w for w in res.warnings)
    assert [p.id for p in _run(projects=[]).doc.projects] == ["auction", "agent"]


@pytest.mark.parametrize("contact,greeting,expected", [
    ("Brayden Smith", "Dear Hiring Manager,", "Dear Brayden,"),
    ("Brayden Smith", "Hi Brayden,", "Hi Brayden,"),
    (None, "Dear Brayden,", "Dear Hiring Manager,"),
    (None, "", "Dear Hiring Manager,"),
])
def test_cover_letter_greeting(contact, greeting, expected):
    res = _run(contact_name=contact, cover_letter={**LETTER, "greeting": greeting})
    assert res.cover_letter.greeting == expected


def test_cover_letter_length_warning_and_missing_letter_rejected():
    res = _run()
    assert any("words" in w for w in res.warnings)
    with pytest.raises(ValueError):
        _run(cover_letter={"greeting": "Dear X,", "paragraphs": ["  "]})


@pytest.mark.parametrize("text", [
    "Built labelling UI with React and Redux.",          # labeling -> labelling
    "Built labelling UI with React and Redux",           # + punctuation
    "Built labeling UI, with React and Redux.",          # punctuation only
    "Built  labeling  UI with React & Redux.".replace("&", "and"),  # whitespace only
])
def test_trivial_bullet_rewrite_reverts_silently(text):
    res = _run(experiences=[{"id": "microsoft", "bullets": [
        {"id": "microsoft-b2", "text": "Kept coverage above 90% with Jest."},
        {"id": "microsoft-b1", "text": text}]}])
    bullets = res.doc.experience("microsoft").bullets
    assert [b.id for b in bullets] == ["microsoft-b2", "microsoft-b1"]  # reorder still applied
    assert bullets[1].text == "Built labeling UI with React and Redux."
    assert res.warnings == _run().warnings  # silent: only the baseline cover-letter length note


def test_spelling_variants_revert():
    base = ResumeDoc(summary="s", skills=[], projects=[], experiences=[_exp(
        "acme", "Optimizing color and center layouts for the organization.", "Built real-time dashboards.")])
    out = TailorOutput.model_validate({"summary": "s", "cover_letter": LETTER, "experiences": [
        {"id": "acme", "bullets": [
            {"id": "acme-b1", "text": "Optimising colour and centre layouts for the organisation."},
            {"id": "acme-b2", "text": "Built real time dashboards."}]}]})
    res = validate(base, out)
    assert res.doc.experience("acme").bullets == base.experiences[0].bullets
    assert not any("Acme" in w for w in res.warnings)


def test_real_bullet_rewrite_kept():
    res = _run(experiences=[{"id": "microsoft", "bullets": [
        {"id": "microsoft-b1", "text": "Built React and Redux labelling UI."},
        {"id": "microsoft-b2", "text": "Kept coverage above 90% with Jest."}]}])
    assert res.doc.experience("microsoft").bullets[0].text == "Built React and Redux labelling UI."


def test_summary_trivial_change_keeps_original():
    res = _run(summary="Full-stack engineer with 6 years' experience in React and TypeScript.")
    assert res.doc.summary != BASE.summary  # real (if small) wording change: "of" dropped
    res = _run(summary="Full stack engineer with 6 years of experience in React and TypeScript")
    assert res.doc.summary == BASE.summary
    assert res.warnings == _run().warnings


def _run_job(**fields):
    data = {"summary": BASE.summary, "cover_letter": LETTER, **fields}
    return validate(BASE, TailorOutput.model_validate(data), job_title="Full Stack Java Developer",
                    ad_text="Java, React, SQL, Hibernate, relational databases.",
                    supported=["SQL", "relational databases"], unsupported=["Hibernate", "Agile development"])


def test_supported_phrase_accepted_in_summary():
    summary = "Full-stack engineer with 6 years of React, TypeScript, SQL and relational databases."
    assert _run(summary=summary).doc.summary == BASE.summary  # SQL is not in the resume vocabulary
    res = _run_job(summary=summary)
    assert res.doc.summary == summary
    assert not any("Summary" in w for w in res.warnings)


def test_unsupported_phrase_rejected_in_summary_and_bullets():
    res = _run_job(summary="Full-stack engineer with 6 years of React, Hibernate and TypeScript.")
    assert res.doc.summary == BASE.summary
    assert any("Hibernate" in w for w in res.warnings)
    res = _run_job(summary="Full-stack engineer with 6 years of Agile development in React and TypeScript.")
    assert res.doc.summary == BASE.summary
    res = _run_job(experiences=[{"id": "sampras", "bullets": [
        {"id": "sampras-b1", "text": "Delivered 9 projects with NestJS, React and Hibernate."}]}])
    assert res.doc.experiences[0].bullets[0].text == "Delivered 9 projects with NestJS and React."


def test_supported_phrase_still_rejects_new_numbers():
    res = _run_job(summary="Full-stack engineer with 8 years of React and relational databases.")
    assert res.doc.summary == BASE.summary


def test_headline_validated_and_fallback():
    res = _run_job(headline="Full Stack Engineer · Java, React, TypeScript")
    assert res.doc.headline == "Full Stack Engineer · Java, React, TypeScript"
    res = _run_job(headline="Lead Full Stack Engineer · Java, Hibernate")
    assert res.doc.headline and "Lead" not in res.doc.headline and "Hibernate" not in res.doc.headline
    assert any("Headline" in w for w in res.warnings)
    assert _run_job().doc.headline  # missing -> deterministic fallback
