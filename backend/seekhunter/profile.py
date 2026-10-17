import re
from dataclasses import dataclass, field
from pathlib import Path

from seekhunter.resume_doc import experience_paths, macro_args, parse_projects
from seekhunter.resume_doc import read_tex as _read
from seekhunter.skills import extract_skills


@dataclass
class Profile:
    skills: set[str]
    summary: str
    titles: list[str]
    skill_lines: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)

    def as_prompt_text(self) -> str:
        return (
            f"Summary: {self.summary}\n"
            f"Skills: {'; '.join(self.skill_lines)}\n"
            f"Past titles: {', '.join(self.titles)}\n"
            f"Highlights: {' | '.join(self.bullets[:12])}"
        )


def _clean(tex: str) -> str:
    tex = tex.replace("\\#", "#").replace("\\&", "&").replace("\\%", "%").replace("--", "-")
    tex = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", tex)
    tex = re.sub(r"\\[a-zA-Z]+\*?\{([^{}]*)\}", r"\1", tex)
    tex = re.sub(r"\\[a-zA-Z]+\*?", " ", tex)
    tex = tex.replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", tex).strip()


def _brace_args(tex: str, macro: str, count: int) -> list[list[str]]:
    """The first `count` brace arguments for every occurrence of \\macro that has all of them."""
    return [args for args in macro_args(tex, macro, count) if len(args) == count]


def load_profile(resume_dir: Path) -> Profile:
    if not resume_dir.is_dir():
        raise FileNotFoundError(f"resume dir not found: {resume_dir}")

    skills_tex = _read(resume_dir / "skills.tex")
    skill_lines = [
        f"{_clean(cat)}: {_clean(vals)}" for cat, vals in _brace_args(skills_tex, "resumeSkillLine", 2)
    ]

    summary_tex = _read(resume_dir / "summary.tex")
    summary = _clean(re.sub(r"\\resumeSection\{[^}]*\}", "", summary_tex))

    # \resumeProject is {name}{stack}{links}{bullets} (older resumes: {name}{stack}{bullets})
    projects = parse_projects(_read(resume_dir / "projects.tex"))
    project_stacks = [p.stack for p in projects]
    project_bullets = [b.text for p in projects for b in p.bullets]

    titles: list[str] = []
    exp_bullets: list[str] = []
    for path in experience_paths(resume_dir):
        for args in _brace_args(_read(path), "resumeExperience", 5):
            titles.append(_clean(args[0]))
            exp_bullets.extend(_clean(b) for b in args[4].split("\\item") if _clean(b))
    titles = list(dict.fromkeys(titles))

    bullets = exp_bullets + project_bullets
    corpus = " ".join(skill_lines + [summary] + project_stacks + bullets)
    return Profile(skills=extract_skills(corpus), summary=summary, titles=titles,
                   skill_lines=skill_lines, bullets=bullets)
