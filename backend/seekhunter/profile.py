import re
from dataclasses import dataclass, field
from pathlib import Path

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


def _strip_comments(tex: str) -> str:
    return "\n".join(line for line in tex.splitlines() if not line.lstrip().startswith("%"))


def _clean(tex: str) -> str:
    tex = tex.replace("\\#", "#").replace("\\&", "&").replace("\\%", "%").replace("--", "-")
    tex = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", tex)
    tex = re.sub(r"\\[a-zA-Z]+\*?\{([^{}]*)\}", r"\1", tex)
    tex = re.sub(r"\\[a-zA-Z]+\*?", " ", tex)
    tex = tex.replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", tex).strip()


def _brace_args(tex: str, macro: str, count: int) -> list[list[str]]:
    """Return the first `count` brace arguments for every occurrence of \\macro (handles nesting)."""
    results: list[list[str]] = []
    for m in re.finditer(r"\\" + macro + r"\b", tex):
        i, args = m.end(), []
        while len(args) < count and i < len(tex):
            while i < len(tex) and tex[i] in " \t\r\n":
                i += 1
            if i >= len(tex) or tex[i] != "{":
                break
            depth, start = 0, i
            while i < len(tex):
                if tex[i] == "{" and tex[i - 1] != "\\":
                    depth += 1
                elif tex[i] == "}" and tex[i - 1] != "\\":
                    depth -= 1
                    if depth == 0:
                        args.append(tex[start + 1 : i])
                        i += 1
                        break
                i += 1
        if len(args) == count:
            results.append(args)
    return results


def _read(path: Path) -> str:
    return _strip_comments(path.read_text(encoding="utf-8")) if path.exists() else ""


def load_profile(resume_dir: Path) -> Profile:
    if not resume_dir.is_dir():
        raise FileNotFoundError(f"resume dir not found: {resume_dir}")

    skills_tex = _read(resume_dir / "skills.tex")
    skill_lines = [
        f"{_clean(cat)}: {_clean(vals)}" for cat, vals in _brace_args(skills_tex, "resumeSkillLine", 2)
    ]

    summary_tex = _read(resume_dir / "summary.tex")
    summary = _clean(re.sub(r"\\resumeSection\{[^}]*\}", "", summary_tex))

    projects_tex = _read(resume_dir / "projects.tex")
    project_args = _brace_args(projects_tex, "resumeProject", 3)
    project_stacks = [_clean(args[1]) for args in project_args]
    project_bullets = [_clean(b) for args in project_args for b in args[2].split("\\item") if _clean(b)]

    titles: list[str] = []
    exp_bullets: list[str] = []
    exp_dir = resume_dir / "experience"
    for path in sorted(exp_dir.glob("*.tex")) if exp_dir.is_dir() else []:
        for args in _brace_args(_read(path), "resumeExperience", 5):
            titles.append(_clean(args[0]))
            exp_bullets.extend(_clean(b) for b in args[4].split("\\item") if _clean(b))

    bullets = exp_bullets + project_bullets
    corpus = " ".join(skill_lines + [summary] + project_stacks + bullets)
    return Profile(skills=extract_skills(corpus), summary=summary, titles=titles,
                   skill_lines=skill_lines, bullets=bullets)
