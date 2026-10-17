from seekhunter import ats_score
from seekhunter.resume_doc import Bullet, Experience, Project, ResumeDoc, SkillLine

EDU = ("\\resumeEducation\n  {Master of Information Technology}\n  {Feb. 2025 -- Jul. 2027}\n"
       "  {Adelaide University}\n  {Adelaide, Australia}\n")


def _doc(summary: str = "Senior React Developer with 5 years building **TypeScript** apps.",
         skills: list[str] | None = None) -> ResumeDoc:
    return ResumeDoc(
        summary=summary,
        skills=[SkillLine(id="languages", category="Languages", items=skills or ["TypeScript", "Python"])],
        experiences=[
            Experience(id="ms", title="Software Engineer", company="Microsoft", location="Taipei",
                       dates="Mar. 2022 -- Apr. 2025",
                       bullets=[Bullet(id="ms-1",
                                       text="Shipped [React](https://react.dev) apps with Jest.")]),
            Experience(id="gc", title="Front-End Developer", company="Gold Crown", location="Taipei",
                       dates="Feb. 2021 -- Feb. 2022", bullets=[Bullet(id="gc-1", text="Built Vue apps.")]),
        ],
        projects=[Project(id="p", name="SeekHunter", stack="FastAPI, React",
                          bullets=[Bullet(id="p-1", text="Job crawler.")])],
        education_tex=EDU)


CONTACT = {"name": "Book Sam", "email": "book@example.com", "phone": "0400"}


def test_resume_to_rm_maps_sections_and_strips_markup():
    rm = ats_score.resume_to_rm(_doc(), CONTACT)
    assert rm["personalInfo"]["email"] == "book@example.com"
    assert rm["summary"] == "Senior React Developer with 5 years building TypeScript apps."
    assert rm["workExperience"][0] == {"title": "Software Engineer", "company": "Microsoft",
                                       "location": "Taipei", "years": "Mar. 2022 -- Apr. 2025",
                                       "description": ["Shipped React apps with Jest."]}
    assert rm["education"][0]["degree"] == "Master of Information Technology"
    assert rm["education"][0]["years"] == "Feb. 2025 – Jul. 2027"
    assert rm["personalProjects"][0]["name"] == "SeekHunter"
    assert rm["additional"]["technicalSkills"] == ["TypeScript", "Python"]


def test_score_breakdown_matches_resume_matcher_formula():
    keywords = {"role": "React Developer", "required_skills": ["React", "TypeScript", "Go", "Kubernetes"],
                "preferred_skills": [], "keywords": ["Jest"]}
    out = ats_score.score_doc(_doc(), keywords, CONTACT)
    b = out["breakdown"]
    assert b["keyword_match"] == 60.0  # React, TypeScript, Jest of 5 distinct terms
    assert b["skills_coverage"] == 50.0  # React, TypeScript of 4 required
    assert b["title_alignment"] == 75.0  # exact title is in the summary, no headline
    assert b["section_completeness"] == 100.0
    assert b["date_consistency"] == 100.0  # every date is "Mon. YYYY"
    expected = 60 * .40 + 50 * .20 + 75 * .15 + 100 * .15 + 100 * .10
    assert out["score"] == round(expected, 1)
    assert out["missing_keywords"] == ["Go", "Kubernetes"]
    assert out["matched_keywords"] == ["React", "TypeScript", "Jest"]


def test_unscorable_components_redistribute_weight():
    out = ats_score.score_doc(_doc(), {"required_skills": ["React"]}, CONTACT)
    assert out["breakdown"]["title_alignment"] is None
    b = out["breakdown"]
    expected = (b["keyword_match"] * .40 + b["skills_coverage"] * .20 + b["section_completeness"] * .15
                + b["date_consistency"] * .10) / .85
    assert out["score"] == round(expected, 1)


def test_tailored_resume_scores_higher_when_it_adds_keywords():
    keywords = ats_score.seekhunter_keywords("Go Developer", matched=["React"], gaps=["Go"])
    base = ats_score.score_doc(_doc(), keywords, CONTACT)
    tailored = ats_score.score_doc(_doc(skills=["TypeScript", "Go"]), keywords, CONTACT)
    assert tailored["score"] > base["score"]
    assert base["missing_keywords"] == ["Go"] and tailored["missing_keywords"] == []


def test_whole_word_matching():
    out = ats_score.score_doc(_doc(), {"keywords": ["Java", "Script"]}, CONTACT)
    assert out["breakdown"]["keyword_match"] == 0.0  # "TypeScript"/"JavaScript" don't count


def test_contact_from_latex(tmp_path):
    (tmp_path / "resume.tex").write_text(
        "\\href{tel:0467364679}{0467364679} \\href{mailto:book@x.com}{book@x.com}\n"
        "{\\fontsize{30}{34}\\selectfont\\resumebold Book Sam}")
    c = ats_score.contact_from_latex(tmp_path)
    assert c["email"] == "book@x.com" and c["phone"] == "0467364679"
    assert ats_score.contact_from_latex(tmp_path / "missing") == {}
