"""Renders a tailored ResumeDoc + cover letter to PDF (Tectonic) and PNG page previews (pdfium)."""

import hashlib
import os
import pwd
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path

from seekhunter.resume_doc import ResumeDoc, escape_tex, read_group, text_to_tex, write_sections
from seekhunter.tailor.models import CoverLetter

COMPILE_TIMEOUT = 240
PNG_SCALE = 1.5
LOG_TAIL = 3000
_IGNORED_DIRS = {"build", ".git", "__pycache__", "node_modules"}
_IGNORED_SUFFIXES = (".pdf", ".aux", ".log", ".xdv", ".fls", ".fdb_latexmk", ".synctex.gz", ".out", ".toc",
                     ".png")
_IGNORED_NAMES = {".DS_Store"}

Compiler = Callable[[Path, str], Path]


class CompileError(Exception):
    pass


def _ignored(name: str, is_dir: bool) -> bool:
    if is_dir:
        return name in _IGNORED_DIRS
    return name in _IGNORED_NAMES or name.endswith(_IGNORED_SUFFIXES)


def _source_files(latex_dir: Path) -> list[Path]:
    files = []
    for root, dirs, names in os.walk(latex_dir):
        dirs[:] = sorted(d for d in dirs if not _ignored(d, True))
        files += [Path(root) / n for n in sorted(names) if not _ignored(n, False)]
    return files


def latex_hash(latex_dir: Path) -> str:
    """Content hash of the resume sources (paths + bytes), ignoring build outputs."""
    h = hashlib.sha256()
    for path in _source_files(latex_dir):
        h.update(path.relative_to(latex_dir).as_posix().encode() + b"\0")
        h.update(path.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def copy_latex(latex_dir: Path, dest: Path) -> None:
    shutil.copytree(latex_dir, dest, ignore=lambda d, names: [
        n for n in names if _ignored(n, (Path(d) / n).is_dir())])


def tectonic_compiler(bin_path: str, timeout: int = COMPILE_TIMEOUT) -> Compiler:
    def compile_tex(work_dir: Path, tex_name: str) -> Path:
        env = dict(os.environ)
        if not env.get("HOME"):  # systemd services have no HOME; Tectonic caches its bundle there
            env["HOME"] = pwd.getpwuid(os.getuid()).pw_dir
        cmd = [bin_path, "-X", "compile", "--untrusted", tex_name]
        try:
            proc = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, timeout=timeout, env=env)
        except FileNotFoundError as e:
            raise CompileError(f"tectonic not found at {bin_path}") from e
        except (OSError, subprocess.TimeoutExpired) as e:
            raise CompileError(f"tectonic failed for {tex_name}: {e}") from e
        pdf = work_dir / (Path(tex_name).stem + ".pdf")
        if proc.returncode != 0 or not pdf.exists():
            log = f"{proc.stdout}\n{proc.stderr}".strip()
            raise CompileError(f"tectonic exit {proc.returncode} for {tex_name}:\n{log[-LOG_TAIL:]}")
        return pdf

    return compile_tex


def page_count(pdf: Path) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        return len(doc)
    finally:
        doc.close()


def render_pages(pdf: Path, out_dir: Path, prefix: str, scale: float = PNG_SCALE) -> int:
    """Write `<prefix>-<n>.png` (1-based) for every page; returns the page count."""
    import pypdfium2 as pdfium

    for old in out_dir.glob(f"{prefix}-*.png"):
        old.unlink()
    doc = pdfium.PdfDocument(str(pdf))
    try:
        for n, page in enumerate(doc, start=1):
            image = page.render(scale=scale).to_pil()
            image.save(out_dir / f"{prefix}-{n}.png", optimize=True)
            page.close()
        return len(doc)
    finally:
        doc.close()


def _preamble(resume_tex: str) -> str:
    idx = resume_tex.find("\\begin{document}")
    if idx < 0:
        raise CompileError("resume.tex has no \\begin{document}")
    return resume_tex[:idx]


HEADLINE_LINE = "\\par\\vspace{-0.1em}{\\fontsize{12}{14}\\selectfont\\resumeHeadline\\par}\\vspace{-0.55em}"
HEADLINE_BLOCK = "\\par{\\centering\\fontsize{12}{15}\\selectfont\\resumeHeadline\\par}"


def with_headline(resume_tex: str, headline: str) -> str:
    """`resume_tex` with a centred role line under the name: defines `\\resumeHeadline` and splices it
    into the `\\resumeHeader` definition just before its `\\end{center}` (so the rule and contact table
    below stay as they are). Without a centred block the line goes at the end of the header; without a
    header macro, right after `\\begin{document}`."""
    define = f"\\newcommand{{\\resumeHeadline}}{{{escape_tex(headline)}}}\n"
    m = re.search(r"\\(?:re)?newcommand\*?\s*\{\\resumeHeader\}", resume_tex)
    body, end = read_group(resume_tex, m.end()) if m else (None, 0)
    if m is None or body is None:
        idx = resume_tex.find("\\begin{document}")
        if idx < 0:
            raise CompileError("resume.tex has no \\begin{document}")
        cut = idx + len("\\begin{document}")
        return resume_tex[:idx] + define + resume_tex[idx:cut] + "\n" + HEADLINE_BLOCK + resume_tex[cut:]
    idx = body.find("\\end{center}")
    if idx >= 0:
        new_body = body[:idx].rstrip() + "\n    " + HEADLINE_LINE + "\n  " + body[idx:]
    else:
        new_body = body.rstrip() + HEADLINE_BLOCK
    start = resume_tex.index("{", m.end())
    tex = resume_tex[:start] + "{" + new_body + "}" + resume_tex[end:]
    return tex[:m.start()] + define + tex[m.start():]


def format_date(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


def cover_letter_tex(resume_tex: str, letter: CoverLetter, *, job_title: str, company: str,
                     contact_name: str | None, location: str, today: date, compact: bool = False) -> str:
    gap, para_gap = ("0.7em", "0.45em") if compact else ("1.1em", "0.7em")
    recipient = [x for x in ((contact_name or "").strip(), company.strip(), location.strip() or "Adelaide SA")
                 if x]
    lines = [
        _preamble(resume_tex).rstrip() + "\n",
        "\\hypersetup{pdftitle={Book Sam Cover Letter}}",
        "% layout: compact" if compact else "% layout: normal",
        "\\begin{document}",
        "\\resumeHeader\\par",
        f"\\vspace{{{gap}}}",
        "\\small" if compact else "",
        f"{format_date(today)}\\par",
        f"\\vspace{{{gap}}}",
        "\\\\\n".join(escape_tex(x) for x in recipient) + "\\par",
        f"\\vspace{{{gap}}}",
        f"{{\\resumebold Re: {escape_tex(job_title)}}}\\par",
        f"\\vspace{{{gap}}}",
        f"{text_to_tex(letter.greeting)}\\par",
    ]
    for p in letter.paragraphs:
        lines += [f"\\vspace{{{para_gap}}}", f"{text_to_tex(p)}\\par"]
    lines += [f"\\vspace{{{gap}}}", f"{text_to_tex(letter.sign_off)}\\par", "\\vspace{0.3em}",
              "Book Sam\\par", "\\end{document}"]
    return "\n".join(line for line in lines if line) + "\n"


def _resume_rel(latex_dir: Path, resume_dir: Path) -> Path:
    try:
        return resume_dir.resolve().relative_to(latex_dir.resolve())
    except ValueError:
        return Path("sections/resume")


def _compile_letter(work: Path, resume_tex: str, letter: CoverLetter, out_dir: Path, compiler: Compiler,
                    warnings: list[str], **kwargs) -> None:
    """Compile `cover_letter.pdf` into `out_dir`, retrying in the compact layout if it spills onto page 2."""
    (work / "cover_letter.tex").write_text(cover_letter_tex(resume_tex, letter, **kwargs), encoding="utf-8")
    letter_pdf = compiler(work, "cover_letter.tex")
    if page_count(letter_pdf) > 1:
        (work / "cover_letter.tex").write_text(
            cover_letter_tex(resume_tex, letter, compact=True, **kwargs), encoding="utf-8")
        letter_pdf = compiler(work, "cover_letter.tex")
        if page_count(letter_pdf) > 1:
            warnings.append("Cover letter runs over one page; consider shortening it.")
    shutil.move(letter_pdf, out_dir / "cover_letter.pdf")


def build_letter(latex_dir: Path, resume_dir: Path, letter: CoverLetter, out_dir: Path, compiler: Compiler, *,
                 job_title: str, company: str, contact_name: str | None, location: str, today: date) -> dict:
    """Re-render only the cover letter in `out_dir` (`cover_letter.pdf`, `cover_letter-<n>.png`).
    Returns `{"pages": int, "warnings": [...]}`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work-letter"
    shutil.rmtree(work, ignore_errors=True)
    warnings: list[str] = []
    try:
        copy_latex(latex_dir, work)
        sections = work / _resume_rel(latex_dir, resume_dir)
        if not sections.is_dir():
            shutil.copytree(resume_dir, sections)
        resume_tex = (work / "resume.tex").read_text(encoding="utf-8")
        _compile_letter(work, resume_tex, letter, out_dir, compiler, warnings, job_title=job_title,
                        company=company, contact_name=contact_name, location=location, today=today)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    pages = render_pages(out_dir / "cover_letter.pdf", out_dir, "cover_letter")
    return {"pages": pages, "warnings": warnings}


def build_tailored(latex_dir: Path, resume_dir: Path, doc: ResumeDoc, letter: CoverLetter, out_dir: Path,
                   compiler: Compiler, *, job_title: str, company: str, contact_name: str | None,
                   location: str, today: date, max_resume_pages: int | None = None) -> dict:
    """Compile the tailored resume and cover letter into `out_dir` (`resume.pdf`, `cover_letter.pdf`,
    `resume-<n>.png`, `cover_letter-<n>.png`). Returns `{"pages": {...}, "warnings": [...], "headline":
    str | None}`; `headline` is what was rendered: a headline that would push the resume past
    `max_resume_pages` is left out (with a warning)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    shutil.rmtree(work, ignore_errors=True)
    warnings: list[str] = []
    try:
        copy_latex(latex_dir, work)
        rel = _resume_rel(latex_dir, resume_dir)
        sections = work / rel
        if not sections.is_dir():
            shutil.copytree(resume_dir, sections)
        write_sections(doc, sections)
        resume_tex = (work / "resume.tex").read_text(encoding="utf-8")
        headline = doc.headline or None
        if headline:
            (work / "resume.tex").write_text(with_headline(resume_tex, headline), encoding="utf-8")
        resume_pdf = compiler(work, "resume.tex")
        if headline and max_resume_pages and (n := page_count(resume_pdf)) > max_resume_pages:
            warnings.append(f"The headline pushed the resume to {n} pages; rendered it without the headline.")
            headline = None
            (work / "resume.tex").write_text(resume_tex, encoding="utf-8")
            resume_pdf = compiler(work, "resume.tex")
        shutil.move(resume_pdf, out_dir / "resume.pdf")

        _compile_letter(work, resume_tex, letter, out_dir, compiler, warnings, job_title=job_title,
                        company=company, contact_name=contact_name, location=location, today=today)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    pages = {"resume": render_pages(out_dir / "resume.pdf", out_dir, "resume"),
             "cover_letter": render_pages(out_dir / "cover_letter.pdf", out_dir, "cover_letter")}
    return {"pages": pages, "warnings": warnings, "headline": headline}
