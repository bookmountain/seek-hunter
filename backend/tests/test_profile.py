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
