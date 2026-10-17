from pathlib import Path

import pytest

from seekhunter.resume_doc import (
    load_resume_doc,
    render_experience_tex,
    render_projects_tex,
    render_skills_tex,
    render_summary_tex,
    tex_to_text,
    text_to_tex,
    write_sections,
)

REAL_LATEX = Path(__file__).resolve().parents[3] / "book-cv" / "latex"
REAL_RESUME = REAL_LATEX / "sections" / "resume"


def test_fixture_doc_structure(fixtures_dir):
    doc = load_resume_doc(fixtures_dir / "resume")
    assert doc.summary == "Full-stack Software Engineer with 5 years of experience in **React** and AI."
    assert [(s.id, s.category) for s in doc.skills] == [
        ("languages", "Languages"), ("cloud-tools", "Cloud & Tools")]
    assert doc.skills[0].items == ["TypeScript", "Python", "C#", "Java"]
    assert [e.id for e in doc.experiences] == ["microsoft"]
    exp = doc.experiences[0]
    assert (exp.title, exp.company, exp.location, exp.dates) == (
        "Software Engineer, VDI Team", "Microsoft", "Taipei, Taiwan", "Mar. 2022 – Apr. 2025")
    assert [(b.id, b.text) for b in exp.bullets] == [
        ("microsoft-b1", "Improved reliability with Jest and React Testing Library.")]
    # 3-arg project (no links arg) is still understood; commented-out project ignored
    assert [p.name for p in doc.projects] == ["Microservice Demo"]
    assert doc.projects[0].id == "microservice-demo"
    assert doc.projects[0].stack == ".NET 8, Next.js 14, RabbitMQ, gRPC"
    assert doc.projects[0].links == ""


def test_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_resume_doc(tmp_path / "nope")


@pytest.mark.parametrize("tex,text", [
    (r"C\# and 90\% \& more", "C# and 90% & more"),
    (r"61--78 ms", "61–78 ms"),
    (r"a---b", "a—b"),
    (r"see \href{https://github.com/x/Y-Z}{Form Recognizer Toolkit}, ok",
     "see [Form Recognizer Toolkit](https://github.com/x/Y-Z), ok"),
    (r"in \textbf{React} now", "in **React** now"),
    (r"a_b \{x\} \$5", "a_b {x} $5"),
    ("one\n   two", "one two"),
])
def test_tex_text_roundtrip(tex, text):
    assert tex_to_text(tex) == text
    assert tex_to_text(text_to_tex(text)) == text


def test_text_to_tex_escapes_specials():
    assert text_to_tex("100% R&D #1 a_b {x} $5 ~ ^ \\") == (
        r"100\% R\&D \#1 a\_b \{x\} \$5 \textasciitilde{} \textasciicircum{} \textbackslash{}")
    assert text_to_tex("2.5 s to 61–78 ms — fast") == "2.5 s to 61--78 ms --- fast"
    assert text_to_tex("[Toolkit](https://github.com/a_b/c%20d)") == (
        r"\href{https://github.com/a_b/c\%20d}{Toolkit}")
    assert text_to_tex("**React** & co") == r"\textbf{React} \& co"


def test_render_sections_match_macros(fixtures_dir):
    doc = load_resume_doc(fixtures_dir / "resume")
    assert render_summary_tex(doc).splitlines()[1] == r"\resumeSection{Professional Summary}"
    assert r"\resumeSkillLine{Cloud \& Tools}{Azure AI Studio, Linux}" in render_skills_tex(doc)
    exp = render_experience_tex(doc.experiences[0])
    assert exp.startswith(
        "%!TEX root = ../../../resume.tex\n\\resumeExperience\n  {Software Engineer, VDI Team}")
    assert "  {Mar. 2022 -- Apr. 2025}" in exp
    assert "    \\item Improved reliability with Jest and React Testing Library." in exp
    proj = render_projects_tex(doc)
    assert "\\resumeProject\n  {Microservice Demo}\n  {.NET 8, Next.js 14, RabbitMQ, gRPC}\n  {}\n" in proj


def _roundtrip(src: Path, tmp_path: Path):
    doc = load_resume_doc(src)
    out = tmp_path / "resume"
    import shutil

    shutil.copytree(src, out)
    write_sections(doc, out)
    return doc, load_resume_doc(out)


def test_fixture_roundtrip(fixtures_dir, tmp_path):
    doc, again = _roundtrip(fixtures_dir / "resume", tmp_path)
    assert again == doc


@pytest.mark.skipif(not REAL_RESUME.is_dir(), reason="book-cv not checked out next to seek-hunter")
def test_real_resume_roundtrip(tmp_path):
    doc, again = _roundtrip(REAL_RESUME, tmp_path)
    assert again == doc
    assert [e.id for e in doc.experiences] == ["sampras", "microsoft", "gold-crown", "dediprog", "kozyguru"]
    assert doc.experiences[1].title == "Software Engineer – VDI Team"
    assert len(doc.experiences[1].bullets) == 8
    assert "97%" in doc.experiences[0].bullets[1].text and "61–78 ms" in doc.experiences[0].bullets[1].text
    assert [p.id for p in doc.projects] == [
        "microsoft-form-recognizer-toolkit", "microservice-demo-auction-platform", "ai-agent-development",
        "ai-web-generator", "ucompass"]
    assert doc.projects[2].links.startswith(r"\resumeLink{https://github.com/bookmountain/ai-agent}")
    assert "[Form Recognizer Toolkit](https://github.com/microsoft/Form-Recognizer-Toolkit)" in (
        doc.projects[0].bullets[0].text)
    assert doc.skills[0].items[2] == "C#"
    assert doc.skills[1].category == "Frontend & Mobile"
    assert "Adelaide University" in doc.education_tex and "Debby King" in doc.referees_tex
