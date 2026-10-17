import pytest

from seekhunter.domain import JobData
from seekhunter.filters import evaluate_exclusions
from seekhunter.settings_model import AppSettings


def job(title="Software Developer", company="Acme", text=""):
    return JobData(source="seek", external_id="1", title=title, company=company, location="Adelaide SA",
                   work_type="part_time", url="u", description_html=f"<p>{text}</p>")


@pytest.mark.parametrize("j, reason", [
    (job(text="Applicants must hold a current NV1 clearance."), "clearance"),
    (job(text="Ability to obtain a Baseline clearance is essential."), "clearance"),
    (job(text="You must be an Australian citizen to apply."), "citizenship"),
    (job(text="Australian citizens or permanent residents only."), "citizenship"),
    (job(text="Australian citizens only. No sponsorship available."), "citizenship"),
    (job(company="BAE Systems Australia"), "defence"),
    (job(text="Join a defence prime delivering naval programs."), "defence"),
    (job(company="Westpac Group"), "bank"),
    (job(company="Talent International", text="Our client, a leading bank, seeks a React dev."), "bank"),
])
def test_excluded(j, reason):
    r = evaluate_exclusions(j, AppSettings())
    assert r.excluded
    assert reason in r.reasons
    assert r.snippets[reason]


@pytest.mark.parametrize("j", [
    job(text="No security clearance required. Work rights in Australia needed."),
    job(text="A security clearance is not required for this role."),
    job(company="ANZAC Medical Centre", text="React developer"),
    job(company="Ingenia Communities", text="TypeScript role"),
    job(text="Great React and Node role, part time."),
])
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
