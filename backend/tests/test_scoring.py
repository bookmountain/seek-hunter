import pytest

from seekhunter.domain import JobData
from seekhunter.scoring import blend, score_job
from seekhunter.settings_model import AppSettings

PROFILE = {"React", "TypeScript", "Node.js", "C#", ".NET", "Azure", "Python", "PostgreSQL", "Docker"}


def job(title="Full Stack Developer", work_type="contract", text=""):
    return JobData(source="seek", external_id="1", title=title, company="Acme", location="Adelaide SA",
                   work_type=work_type, url="u", description_html=f"<p>{text}</p>")


def test_flexible_work_beats_full_time():
    text = "React TypeScript Node.js"
    assert score_job(job(work_type="contract", text=text), PROFILE, AppSettings()).rule_score > \
        score_job(job(work_type="full_time", text=text), PROFILE, AppSettings()).rule_score


def test_skill_points_saturate_and_report_matches():
    r = score_job(job(text="React TypeScript Node.js C# .NET Azure Python PostgreSQL Docker"), PROFILE,
                  AppSettings())
    assert r.matched_skills == sorted(PROFILE)
    assert r.rule_score == 35 + 50 + 15


def test_role_penalty():
    good = score_job(job(title="Software Developer"), PROFILE, AppSettings()).rule_score
    bad = score_job(job(title="Principal Engineer"), PROFILE, AppSettings()).rule_score
    assert good - bad == 15


def test_hours_flag():
    r = score_job(job(work_type="part_time", text="Minimum 30 hours per week"), PROFILE, AppSettings())
    assert "hours" in r.flags
    r2 = score_job(job(work_type="part_time", text="20 hours per week"), PROFILE, AppSettings())
    assert "hours" not in r2.flags
    assert "flexible" in r2.flags


def test_blend():
    assert blend(80, None) == 80
    assert blend(80, 50) == 68


@pytest.mark.parametrize("text", [
    "37.5 hours per week",
    "76 hours per fortnight",
    "30 hours weekly",
    "0.8 FTE",
    "4 days a week",
])
def test_hours_flag_variants_trigger(text):
    r = score_job(job(work_type="part_time", text=text), PROFILE, AppSettings())
    assert "hours" in r.flags, text


@pytest.mark.parametrize("text", [
    "20 hours per week",
    "40 hours per fortnight",
    "0.5 FTE",
    "3 days per week",
])
def test_hours_flag_variants_do_not_trigger(text):
    r = score_job(job(work_type="part_time", text=text), PROFILE, AppSettings())
    assert "hours" not in r.flags, text


def test_directory_services_not_penalised_as_director():
    normal = score_job(job(title="Directory Services Engineer"), PROFILE, AppSettings()).rule_score
    penalized = score_job(job(title="Director"), PROFILE, AppSettings()).rule_score
    assert normal > penalized


def test_years_experience_penalty_matches_digit_plus_years():
    penalized = score_job(job(text="Minimum 15+ years experience required"), PROFILE, AppSettings())
    clean = score_job(job(text="Great team, flexible hours"), PROFILE, AppSettings())
    assert penalized.rule_score < clean.rule_score


def test_it_support_roles_are_boosted_not_penalised():
    support = score_job(job(title="IT Support Officer"), PROFILE, AppSettings()).rule_score
    plain = score_job(job(title="Operations Analyst"), PROFILE, AppSettings()).rule_score
    assert support - plain == 10
