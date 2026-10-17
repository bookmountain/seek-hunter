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
