"""Structured model of Book's `book-cv` LaTeX resume sections.

`load_resume_doc` parses `sections/resume` into a `ResumeDoc` with stable ids; the `render_*`
functions turn a (possibly tailored) doc back into section files that use the resume's own macros
(`\\resumeSection`, `\\resumeSkillLine`, `\\resumeExperience`, `\\resumeProject`).

Text fields hold plain text (LaTeX unescaped) so the LLM sees readable prose. Two inline constructs
survive the round trip: `\\href{url}{label}` <-> `[label](url)` and `\\textbf{x}` <-> `**x**`.
Dashes map `--` <-> en dash and `---` <-> em dash; `~` <-> no-break space.
"""

import re
from pathlib import Path

from pydantic import BaseModel, Field

NBSP = "\u00a0"


# --------------------------------------------------------------------------- low-level tex helpers

def strip_comments(tex: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*", "", line) for line in tex.splitlines())


def read_tex(path: Path) -> str:
    return strip_comments(path.read_text(encoding="utf-8")) if path.exists() else ""


def _skip_ws(tex: str, i: int) -> int:
    while i < len(tex) and tex[i] in " \t\r\n":
        i += 1
    return i


def read_group(tex: str, i: int) -> tuple[str | None, int]:
    """Read one `{...}` group starting at (or after whitespace from) `i`, honouring nesting and
    backslash escapes. Returns (content, index after the closing brace) or (None, i) if no group."""
    j = _skip_ws(tex, i)
    if j >= len(tex) or tex[j] != "{":
        return None, i
    depth, k = 0, j
    while k < len(tex):
        c = tex[k]
        if c == "\\":
            k += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return tex[j + 1 : k], k + 1
        k += 1
    return None, i


def macro_args(tex: str, macro: str, max_count: int) -> list[list[str]]:
    """Up to `max_count` brace arguments for every occurrence of `\\macro` (fewer if fewer follow)."""
    results: list[list[str]] = []
    for m in re.finditer(r"\\" + macro + r"(?![A-Za-z])", tex):
        i, args = m.end(), []
        while len(args) < max_count:
            content, i = read_group(tex, i)
            if content is None:
                break
            args.append(content)
        results.append(args)
    return results


# --------------------------------------------------------------------------- tex <-> text

_SYMBOL_WORDS = {"textbackslash": "\\", "textasciitilde": "~", "textasciicircum": "^", "textbar": "|",
                 "textendash": "–", "textemdash": "—", "ldots": "…", "dots": "…"}


def _unescape_url(url: str) -> str:
    return re.sub(r"\\([%#&_~$])", r"\1", url.strip())


def _escape_url(url: str) -> str:
    return url.replace("%", "\\%").replace("#", "\\#")


def _tex_to_text_raw(tex: str) -> str:
    out: list[str] = []
    i, n = 0, len(tex)
    while i < n:
        c = tex[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+)\*?", tex[i:])
            if m:
                name = m.group(1)
                i += m.end()
                if name == "href":
                    url, i = read_group(tex, i)
                    label, i = read_group(tex, i)
                    out.append(f"[{tex_to_text(label or '')}]({_unescape_url(url or '')})")
                elif name == "textbf":
                    arg, i = read_group(tex, i)
                    out.append(f"**{tex_to_text(arg or '')}**")
                elif name in _SYMBOL_WORDS:
                    out.append(_SYMBOL_WORDS[name])
                    if tex.startswith("{}", i):
                        i += 2
                elif name == "item":
                    out.append(" ")
                else:
                    arg, j = read_group(tex, i)
                    if arg is not None:
                        out.append(_tex_to_text_raw(arg))
                        i = j
                    else:
                        out.append(" ")
                continue
            nxt = tex[i + 1] if i + 1 < n else ""
            out.append(" " if nxt in ("\\", " ", "\n", "") else nxt)
            i += 2
            continue
        if c in "{}":
            i += 1
            continue
        if c == "~":
            out.append(NBSP)
        elif c == "-" and tex.startswith("---", i):
            out.append("—")
            i += 3
            continue
        elif c == "-" and tex.startswith("--", i):
            out.append("–")
            i += 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def tex_to_text(tex: str) -> str:
    return re.sub(r"[ \t\r\n]+", " ", _tex_to_text_raw(tex)).strip()


_ESCAPES = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "#": r"\#", "$": r"\$", "%": r"\%", "&": r"\&",
    "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "–": "--", "—": "---", NBSP: "~",
}
_INLINE = re.compile(r"\[([^\]\n]+)\]\(((?:https?://|mailto:)[^)\s]+)\)|\*\*(.+?)\*\*")


def escape_tex(text: str) -> str:
    return "".join(_ESCAPES.get(c, c) for c in text)


def text_to_tex(text: str) -> str:
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        out.append(escape_tex(text[pos : m.start()]))
        if m.group(1) is not None:
            out.append(f"\\href{{{_escape_url(m.group(2))}}}{{{escape_tex(m.group(1))}}}")
        else:
            out.append(f"\\textbf{{{escape_tex(m.group(3))}}}")
        pos = m.end()
    out.append(escape_tex(text[pos:]))
    return "".join(out)


# --------------------------------------------------------------------------- model

class Bullet(BaseModel):
    id: str
    text: str


class SkillLine(BaseModel):
    id: str
    category: str
    items: list[str]


class Experience(BaseModel):
    id: str
    title: str
    company: str
    location: str
    dates: str
    bullets: list[Bullet]


class Project(BaseModel):
    id: str
    name: str
    stack: str
    links: str = ""  # raw tex, passed through untouched
    bullets: list[Bullet]


DEFAULT_HEADINGS = {"summary": "Professional Summary", "skills": "Skills", "experience": "Experience",
                    "projects": "Projects"}


class ResumeDoc(BaseModel):
    summary: str
    skills: list[SkillLine]
    experiences: list[Experience]
    projects: list[Project]
    education_tex: str = ""
    referees_tex: str = ""
    headings: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_HEADINGS))

    def corpus(self) -> str:
        """All visible resume text (for "is this term already in the resume?" checks)."""
        parts = [self.summary]
        parts += [f"{s.category}: {', '.join(s.items)}" for s in self.skills]
        for e in self.experiences:
            parts += [e.title, e.company] + [b.text for b in e.bullets]
        for p in self.projects:
            parts += [p.name, p.stack] + [b.text for b in p.bullets]
        return "\n".join(parts)

    def experience(self, exp_id: str) -> Experience | None:
        return next((e for e in self.experiences if e.id == exp_id), None)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-") or "x"


def _unique(base: str, seen: set[str]) -> str:
    cand, n = base, 2
    while cand in seen:
        cand, n = f"{base}-{n}", n + 1
    seen.add(cand)
    return cand


def _split_items(text: str) -> list[str]:
    items, depth, cur = [], 0, []
    for c in text:
        if c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        if c == "," and depth == 0:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    items.append("".join(cur))
    return [i.strip() for i in items if i.strip()]


def _bullets(tex: str, prefix: str) -> list[Bullet]:
    texts = [tex_to_text(part) for part in re.split(r"\\item(?![A-Za-z])", tex)[1:]]
    return [Bullet(id=f"{prefix}-b{n}", text=t) for n, t in enumerate((t for t in texts if t), start=1)]


def _heading(tex: str) -> str | None:
    args = macro_args(tex, "resumeSection", 1)
    return tex_to_text(args[0][0]) if args and args[0] else None


def experience_paths(resume_dir: Path) -> list[Path]:
    """Experience files in resume order, following `experience.tex`'s `\\input{...}` lines.

    Falls back to a sorted glob of `experience/*.tex` if `experience.tex` is missing.
    """
    exp_dir = resume_dir / "experience"
    exp_tex = resume_dir / "experience.tex"
    if exp_tex.exists():
        paths: list[Path] = []
        for m in re.finditer(r"\\input\{([^}]*)\}", read_tex(exp_tex)):
            name = m.group(1).strip().rsplit("/", 1)[-1]
            if not name.endswith(".tex"):
                name += ".tex"
            path = exp_dir / name
            if path.exists():
                paths.append(path)
        return paths
    return sorted(exp_dir.glob("*.tex")) if exp_dir.is_dir() else []


def _with_inputs(resume_dir: Path, name: str) -> str:
    """A section file plus the files it `\\input`s (by basename from `<name>/`), comment-stripped."""
    tex = read_tex(resume_dir / f"{name}.tex")
    parts = [tex]
    for m in re.finditer(r"\\input\{([^}]*)\}", tex):
        base = m.group(1).strip().rsplit("/", 1)[-1]
        parts.append(read_tex(resume_dir / name / (base if base.endswith(".tex") else base + ".tex")))
    return "\n".join(p.strip() for p in parts if p.strip())


def parse_projects(projects_tex: str) -> list[Project]:
    projects, seen = [], set()
    for args in macro_args(projects_tex, "resumeProject", 4):
        if len(args) == 4:
            name, stack, links, body = args
        elif len(args) == 3:  # older 3-arg form: {name}{stack}{bullets}
            name, stack, body = args
            links = ""
        else:
            continue
        pid = _unique(slugify(tex_to_text(name)), seen)
        projects.append(Project(id=pid, name=tex_to_text(name), stack=tex_to_text(stack),
                                links=links.strip(), bullets=_bullets(body, pid)))
    return projects


def load_resume_doc(resume_dir: Path) -> ResumeDoc:
    if not resume_dir.is_dir():
        raise FileNotFoundError(f"resume dir not found: {resume_dir}")
    headings = dict(DEFAULT_HEADINGS)

    summary_tex = read_tex(resume_dir / "summary.tex")
    headings["summary"] = _heading(summary_tex) or headings["summary"]
    summary = tex_to_text(re.sub(r"\\resumeSection\s*\{[^}]*\}", "", summary_tex))

    skills_tex = read_tex(resume_dir / "skills.tex")
    headings["skills"] = _heading(skills_tex) or headings["skills"]
    skills, seen = [], set()
    for args in macro_args(skills_tex, "resumeSkillLine", 2):
        if len(args) == 2:
            cat = tex_to_text(args[0])
            skills.append(SkillLine(id=_unique(slugify(cat), seen), category=cat,
                                    items=_split_items(tex_to_text(args[1]))))

    headings["experience"] = _heading(read_tex(resume_dir / "experience.tex")) or headings["experience"]
    experiences = []
    for path in experience_paths(resume_dir):
        for args in macro_args(read_tex(path), "resumeExperience", 5)[:1]:
            if len(args) == 5:
                title, company, location, dates, body = args
                experiences.append(Experience(
                    id=path.stem, title=tex_to_text(title), company=tex_to_text(company),
                    location=tex_to_text(location), dates=tex_to_text(dates),
                    bullets=_bullets(body, path.stem)))

    projects_tex = read_tex(resume_dir / "projects.tex")
    headings["projects"] = _heading(projects_tex) or headings["projects"]

    return ResumeDoc(summary=summary, skills=skills, experiences=experiences,
                     projects=parse_projects(projects_tex),
                     education_tex=_with_inputs(resume_dir, "education"),
                     referees_tex=_with_inputs(resume_dir, "referees"), headings=headings)


# --------------------------------------------------------------------------- render

def _section(heading: str, root: str = "../../resume.tex") -> str:
    return f"%!TEX root = {root}\n\\resumeSection{{{escape_tex(heading)}}}\n\n"


def _items(bullets: list[Bullet]) -> str:
    lines = "".join(f"    \\item {text_to_tex(b.text)}\n" for b in bullets)
    return "  {\n" + lines + "  }\n"


def render_summary_tex(doc: ResumeDoc) -> str:
    return _section(doc.headings.get("summary", "Professional Summary")) + text_to_tex(doc.summary) + "\n"


def render_skills_tex(doc: ResumeDoc) -> str:
    lines = "".join(
        f"\\resumeSkillLine{{{text_to_tex(s.category)}}}{{{text_to_tex(', '.join(s.items))}}}\n"
        for s in doc.skills)
    return _section(doc.headings.get("skills", "Skills")) + lines


def render_experience_tex(exp: Experience) -> str:
    fields = "".join(f"  {{{text_to_tex(v)}}}\n" for v in (exp.title, exp.company, exp.location, exp.dates))
    return "%!TEX root = ../../../resume.tex\n\\resumeExperience\n" + fields + _items(exp.bullets)


def render_projects_tex(doc: ResumeDoc) -> str:
    blocks = [
        f"\\resumeProject\n  {{{text_to_tex(p.name)}}}\n  {{{text_to_tex(p.stack)}}}\n  {{{p.links}}}\n"
        + _items(p.bullets)
        for p in doc.projects
    ]
    return _section(doc.headings.get("projects", "Projects")) + "\n".join(blocks)


def write_sections(doc: ResumeDoc, resume_dir: Path) -> None:
    """Regenerate summary/skills/projects and each experience file under `resume_dir` from `doc`.
    `experience.tex`, education and referees are left untouched."""
    (resume_dir / "summary.tex").write_text(render_summary_tex(doc), encoding="utf-8")
    (resume_dir / "skills.tex").write_text(render_skills_tex(doc), encoding="utf-8")
    (resume_dir / "projects.tex").write_text(render_projects_tex(doc), encoding="utf-8")
    (resume_dir / "experience").mkdir(exist_ok=True)
    for exp in doc.experiences:
        (resume_dir / "experience" / f"{exp.id}.tex").write_text(render_experience_tex(exp), encoding="utf-8")
