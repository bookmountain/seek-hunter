from seekhunter.profile import load_profile


def test_load_profile_extracts_skills_titles_summary(fixtures_dir):
    p = load_profile(fixtures_dir / "resume")
    assert {"TypeScript", "Python", "C#", "Java", "Azure", "Linux", ".NET", "Next.js", "RabbitMQ",
            "gRPC", "Docker", "Jest", "React"} <= p.skills
    assert "Fortran" not in p.summary and "Cobol" not in " ".join(p.skill_lines)
    assert p.titles == ["Software Engineer, VDI Team"]
    assert p.summary.startswith("Full-stack Software Engineer with 5 years")
    assert "\\textbf" not in p.summary


def test_missing_dir_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_profile(tmp_path / "nope")


def test_experience_tex_input_order_skips_commented_entries(fixtures_dir):
    p = load_profile(fixtures_dir / "resume")
    assert p.titles == ["Software Engineer, VDI Team"]
    assert "Classified Analyst" not in p.titles


def test_trailing_percent_comment_is_stripped(tmp_path):
    resume_dir = tmp_path / "resume"
    resume_dir.mkdir()
    (resume_dir / "skills.tex").write_text(
        "\\resumeSkillLine{Languages}{TypeScript} % secret: Cobol\n"
    )
    p = load_profile(resume_dir)
    assert "Cobol" not in " ".join(p.skill_lines)
    assert p.skill_lines == ["Languages: TypeScript"]


def test_titles_deduped_keeping_order(tmp_path):
    resume_dir = tmp_path / "resume"
    exp_dir = resume_dir / "experience"
    exp_dir.mkdir(parents=True)
    entry = (
        "\\resumeExperience\n"
        "  {Front-End Developer}\n"
        "  {Acme}\n"
        "  {Here}\n"
        "  {Jan. 2020 -- Feb. 2021}\n"
        "  {\n"
        "    \\item Did things.\n"
        "  }\n"
    )
    (exp_dir / "a.tex").write_text(entry)
    (exp_dir / "b.tex").write_text(entry)
    p = load_profile(resume_dir)
    assert p.titles == ["Front-End Developer"]
