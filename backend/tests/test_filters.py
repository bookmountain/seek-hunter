import pytest

from seekhunter.domain import JobData
from seekhunter.filters import evaluate_exclusions
from seekhunter.settings_model import AppSettings


def job(title="Software Developer", company="Acme", text=""):
    return JobData(
        source="seek",
        external_id="1",
        title=title,
        company=company,
        location="Adelaide SA",
        work_type="part_time",
        url="u",
        description_html=f"<p>{text}</p>",
    )


def job_html(title="Software Developer", company="Acme", html=""):
    return JobData(
        source="seek",
        external_id="1",
        title=title,
        company=company,
        location="Adelaide SA",
        work_type="part_time",
        url="u",
        description_html=html,
    )


@pytest.mark.parametrize(
    "j, reason",
    [
        (job(text="Applicants must hold a current NV1 clearance."), "clearance"),
        (job(text="Ability to obtain a Baseline clearance is essential."), "clearance"),
        (job(text="You must be an Australian citizen to apply."), "citizenship"),
        (job(text="Australian citizens or permanent residents only."), "citizenship"),
        (job(text="Australian citizens only. No sponsorship available."), "citizenship"),
        (job(company="BAE Systems Australia"), "defence"),
        (job(text="Join a defence prime delivering naval programs."), "defence"),
        (job(company="Westpac Group"), "bank"),
    ],
)
def test_excluded(j, reason):
    r = evaluate_exclusions(j, AppSettings())
    assert r.excluded
    assert reason in r.reasons
    assert r.snippets[reason]


@pytest.mark.parametrize(
    "j",
    [
        job(text="No security clearance required. Work rights in Australia needed."),
        job(text="A security clearance is not required for this role."),
        job(company="ANZAC Medical Centre", text="React developer"),
        job(company="Ingenia Communities", text="TypeScript role"),
        job(text="Great React and Node role, part time."),
    ],
)
def test_not_excluded(j):
    r = evaluate_exclusions(j, AppSettings())
    assert not r.excluded, r.reasons


def test_allowlist_overrides_employer_rules_not_clearance():
    s = AppSettings(employer_allowlist=["Westpac"])
    assert not evaluate_exclusions(job(company="Westpac"), s).excluded
    assert evaluate_exclusions(job(company="Westpac", text="NV1 clearance needed"), s).excluded


def test_fintech_toggle():
    j = job(text="Fast-growing fintech startup")
    assert not evaluate_exclusions(j, AppSettings()).excluded
    assert "fintech" in evaluate_exclusions(j, AppSettings(exclude_fintech=True)).reasons


@pytest.mark.parametrize(
    "j, reason",
    [
        (
            job_html(html="<ul><li>No visa sponsorship</li><li>Security clearance required</li></ul>"),
            "clearance",
        ),
        (job_html(html="<li>Hybrid, no weekends</li><li>NV1 clearance required</li>"), "clearance"),
        (job(text="No visa sponsorship: Australian citizens only"), "citizenship"),
        (job(text="No sponsorship available, Australian citizens only"), "citizenship"),
        (job(text="Australian citizen with no criminal record, NV1 clearance"), "clearance"),
        (job(text="Non-negotiable: NV1 clearance"), "clearance"),
        (job(text="Not suitable for applicants without NV1 clearance"), "clearance"),
        (job(text="Must hold NV1. Not required: degree"), "clearance"),
    ],
)
def test_negation_does_not_leak_across_bullets_or_sentences(j, reason):
    r = evaluate_exclusions(j, AppSettings())
    assert r.excluded
    assert reason in r.reasons


@pytest.mark.parametrize(
    "j",
    [
        job(text="Security clearance not essential"),
        job(text="No security clearance required"),
        job(text="A security clearance is not required for this role."),
    ],
)
def test_genuine_negation_still_suppresses_exclusion(j):
    r = evaluate_exclusions(j, AppSettings())
    assert not r.excluded, r.reasons


def test_banks_are_tagged_not_excluded_except_westpac_group():
    from seekhunter.scoring import score_job

    for company in ("Commonwealth Bank", "Bendigo Bank", "People First Bank", "Some Regional Bank Ltd"):
        assert not evaluate_exclusions(job(company=company), AppSettings()).excluded, company
        assert "bank" in score_job(job(company=company), set(), AppSettings()).flags, company
    for company in ("BankSA", "St.George Bank", "Bank of Melbourne"):
        r = evaluate_exclusions(job(company=company), AppSettings())
        assert r.reasons == ["bank"] and "student visa" in r.snippets["bank"], company
    ad = job(company="Talent International", text="Our client, a leading bank, seeks a React dev.")
    assert not evaluate_exclusions(ad, AppSettings()).excluded
    assert "bank" in score_job(ad, set(), AppSettings()).flags


def test_exclude_banks_setting_restores_blanket_exclusion():
    on = AppSettings(exclude_banks=True)
    assert "bank" in evaluate_exclusions(job(company="People First Bank"), on).reasons
    ad = job(company="Talent International", text="Our client, a leading bank, seeks a React dev.")
    assert "bank" in evaluate_exclusions(ad, on).reasons
    assert not evaluate_exclusions(job(company="Peoplebank"), on).excluded


def test_short_bank_acronyms_only_match_at_the_start():
    from seekhunter.scoring import score_job

    assert "bank" in score_job(job(company="ANZ Banking Group"), set(), AppSettings()).flags
    assert "bank" not in score_job(job(company="Allume ANZ"), set(), AppSettings()).flags
    assert "bank" in score_job(job(company="CBA"), set(), AppSettings()).flags


def test_citizenship_wording_still_excludes_bank_ads():
    r = evaluate_exclusions(job(company="Commonwealth Bank", text="Australian citizens only."), AppSettings())
    assert r.reasons == ["citizenship"]


OFF_TOPIC = [
    "Occupational Therapist - Graduate/Newly Qualified",
    "CORE PHYSIOTHERAPY NEW GRADUATE PHYSIOTHERAPIST",
    "Plant Operator",
    "Senior Consultant - Indirect Tax",
    "Graduate Accountant | Audit & Assurance",
    "Civil Designer",
    "Stevedore - Adelaide",
    "In-house Property and Commercial Lawyer 3-9 PAE",
    "Retail Leadership - Graduate Program",
    "Toolmaker",
    "Underwriter",
    "Office Manager",
    "Property Developer - Residential",
    "CNC MACHINIST - CAM PROGRAMMER - CUSTOMER SERVICE",
    "Business Development Manager",
]
ON_TOPIC = [
    "Full Stack (Java) Developer",
    "Information Systems Support Officer",
    "Data Systems and Reporting Officer",
    "Solutions Architect",
    "IT Support Officer (Casual)",
    "Software Engineer - AI",
    "Service Desk Analyst",
    "Junior Frontend Developer",
    "Azure Cloud Developer",
    "QA Engineers",
    "Automation Developer",
    "Field Technician - IT",
]


@pytest.mark.parametrize("title", OFF_TOPIC)
def test_off_topic_titles_excluded(title):
    r = evaluate_exclusions(job(title=title, text="Great team, competitive salary."), AppSettings())
    assert r.reasons == ["off_topic"], title


@pytest.mark.parametrize("title", ON_TOPIC)
def test_it_titles_not_off_topic(title):
    assert not evaluate_exclusions(job(title=title, text="Great team."), AppSettings()).excluded, title


def test_vague_title_with_tech_heavy_ad_is_kept():
    r = evaluate_exclusions(
        job(title="Engineer", text="React TypeScript Node.js PostgreSQL Docker"), AppSettings()
    )
    assert not r.excluded


def test_off_topic_can_be_disabled():
    s = AppSettings(exclude_off_topic=False)
    assert not evaluate_exclusions(job(title="Plant Operator", text="x"), s).excluded
