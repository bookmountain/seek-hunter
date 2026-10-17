import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from seekhunter.resume_doc import load_resume_doc
from seekhunter.tailor import current, render
from seekhunter.tailor.models import CoverLetter
from tests.pdf_helpers import FakeCompiler, write_pdf

REAL_LATEX = Path(__file__).resolve().parents[3] / "book-cv" / "latex"

RESUME_TEX = r"""\documentclass{article}
\usepackage{fontspec}
\newcommand{\resumeHeader}{Book Sam}
\begin{document}
\resumeHeader
\input{sections/resume/summary.tex}
\end{document}
"""

LETTER = CoverLetter(greeting="Dear Brayden,", paragraphs=["I cut costs by 50% & more.", "Second."],
                     sign_off="Kind regards,")


@pytest.fixture
def latex_dir(tmp_path, fixtures_dir):
    d = tmp_path / "latex"
    shutil.copytree(fixtures_dir / "resume", d / "sections" / "resume")
    (d / "resume.tex").write_text(RESUME_TEX)
    (d / "build").mkdir()
    (d / "build" / "resume.pdf").write_text("stale")
    return d


def test_cover_letter_tex_reuses_preamble_and_header():
    tex = render.cover_letter_tex(RESUME_TEX, LETTER, job_title="React Dev #2", company="Acme & Co",
                                  contact_name="Brayden Smith", location="", today=date(2026, 10, 17))
    assert tex.startswith("\\documentclass{article}\n\\usepackage{fontspec}\n\\newcommand{\\resumeHeader}")
    assert tex.count("\\begin{document}") == 1
    body = tex.split("\\begin{document}", 1)[1]
    assert body.lstrip().startswith("\\resumeHeader\\par")
    assert "17 October 2026" in body
    assert "Brayden Smith\\\\\nAcme \\& Co\\\\\nAdelaide SA" in body
    assert "Re: React Dev \\#2" in body
    assert "I cut costs by 50\\% \\& more." in body
    assert body.rstrip().endswith("Book Sam\\par\n\\end{document}")


def test_cover_letter_tex_without_contact_uses_job_location():
    tex = render.cover_letter_tex(RESUME_TEX, LETTER, job_title="Dev", company="Acme", contact_name=None,
                                  location="Mawson Lakes, Adelaide SA", today=date(2026, 1, 5))
    assert "5 January 2026" in tex
    assert "Acme\\\\\nMawson Lakes, Adelaide SA" in tex


def test_latex_hash_ignores_build_outputs(latex_dir):
    h = render.latex_hash(latex_dir)
    (latex_dir / "build" / "resume.pdf").write_text("changed")
    (latex_dir / "resume.pdf").write_text("x")
    assert render.latex_hash(latex_dir) == h
    (latex_dir / "sections" / "resume" / "summary.tex").write_text("new")
    assert render.latex_hash(latex_dir) != h


def test_render_pages_writes_pngs(tmp_path):
    pdf = tmp_path / "a.pdf"
    write_pdf(pdf, 2)
    assert render.render_pages(pdf, tmp_path, "resume") == 2
    assert Image.open(tmp_path / "resume-1.png").size == (90, 128)  # scale 1.5 of 60x85pt
    assert (tmp_path / "resume-2.png").exists()


def test_build_tailored_outputs(latex_dir, tmp_path, fixtures_dir):
    doc = load_resume_doc(fixtures_dir / "resume")
    doc.summary = "Tailored summary with 100% focus."
    out = tmp_path / "out"
    compiler = FakeCompiler({"resume.tex": 2})
    info = render.build_tailored(latex_dir, latex_dir / "sections" / "resume", doc, LETTER, out, compiler,
                                 job_title="Dev", company="Acme", contact_name=None, location="Adelaide SA",
                                 today=date(2026, 10, 17))
    assert info["pages"] == {"resume": 2, "cover_letter": 1}
    for name in ("resume.pdf", "cover_letter.pdf", "resume-1.png", "resume-2.png", "cover_letter-1.png"):
        assert (out / name).exists(), name
    assert [name for _, name in compiler.calls] == ["resume.tex", "cover_letter.tex"]
    assert not (out / "work").exists()  # work dir cleaned up
    # the original latex dir is untouched
    assert "Tailored" not in (latex_dir / "sections" / "resume" / "summary.tex").read_text()


def test_build_tailored_compacts_two_page_cover_letter(latex_dir, tmp_path, fixtures_dir):
    doc = load_resume_doc(fixtures_dir / "resume")
    seen = []

    def compiler(work_dir, tex_name):
        if tex_name == "cover_letter.tex":
            seen.append("compact" in (work_dir / tex_name).read_text())
        pdf = work_dir / tex_name.replace(".tex", ".pdf")
        write_pdf(pdf, 2 if seen == [False] and tex_name == "cover_letter.tex" else 1)
        return pdf

    info = render.build_tailored(latex_dir, latex_dir / "sections" / "resume", doc, LETTER, tmp_path / "o",
                                 compiler, job_title="Dev", company="Acme", contact_name=None, location="",
                                 today=date(2026, 10, 17))
    assert seen == [False, True]
    assert info["pages"]["cover_letter"] == 1


def test_tectonic_compiler_failure_includes_log(tmp_path, monkeypatch):
    def fake_run(cmd, **kw):
        assert cmd[:4] == ["/x/tectonic", "-X", "compile", "--untrusted"]
        assert kw["cwd"] == tmp_path and kw["timeout"] == 240
        return subprocess.CompletedProcess(cmd, 1, "", "error: resume.tex:12: Undefined control sequence")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(render.CompileError, match="Undefined control sequence"):
        render.tectonic_compiler("/x/tectonic")(tmp_path, "resume.tex")


def test_tectonic_compiler_missing_binary(tmp_path):
    with pytest.raises(render.CompileError, match="not found"):
        render.tectonic_compiler(str(tmp_path / "nope"))(tmp_path, "resume.tex")


def test_ensure_current_caches_by_hash(latex_dir, tmp_path):
    compiler = FakeCompiler({"resume.tex": 2})
    data = tmp_path / "data"
    info = current.ensure_current(latex_dir, data, compiler)
    assert info["pages"] == 2 and info["hash"] == render.latex_hash(latex_dir)
    d = current.current_dir(data, info["hash"])
    assert (d / "resume.pdf").exists() and (d / "resume-2.png").exists()
    assert current.ensure_current(latex_dir, data, compiler) == info
    assert len(compiler.calls) == 1
    assert current.read_current(data, info["hash"]) == info
    assert current.read_current(data, "deadbeef") is None
    assert current.read_current(data, "../etc") is None


@pytest.mark.skipif(shutil.which("tectonic") is None or not REAL_LATEX.is_dir(),
                    reason="needs tectonic and book-cv checked out")
def test_real_tailored_resume_compiles(tmp_path):
    doc = load_resume_doc(REAL_LATEX / "sections" / "resume")
    doc.experiences[1].bullets = doc.experiences[1].bullets[:4]
    doc.skills[0].items = list(reversed(doc.skills[0].items))
    doc.projects = doc.projects[1:4]
    letter = CoverLetter(greeting="Dear Hiring Manager,",
                         paragraphs=["I build React and TypeScript apps & APIs, 97% faster. " * 6] * 4)
    info = render.build_tailored(REAL_LATEX, REAL_LATEX / "sections" / "resume", doc, letter, tmp_path / "o",
                                 render.tectonic_compiler(shutil.which("tectonic")), job_title="Developer",
                                 company="Acme", contact_name=None, location="Adelaide SA",
                                 today=date(2026, 10, 17))
    assert info["pages"]["cover_letter"] == 1
    assert 1 <= info["pages"]["resume"] <= 3
    assert (tmp_path / "o" / "resume.pdf").stat().st_size > 10_000


REAL_HEADER = r"""\documentclass{article}
\newcommand{\resumeHeader}{%
  \begin{center}
    {\fontsize{30}{34}\selectfont Book Sam}
  \end{center}
  \hrule
  contact table
}
\begin{document}
\resumeHeader
\end{document}
"""


def test_with_headline_inserts_line_under_name_inside_header():
    tex = render.with_headline(REAL_HEADER, "Full Stack Engineer · Java & React")
    pre, body = tex.split("\\begin{document}")
    assert "\\newcommand{\\resumeHeadline}{Full Stack Engineer · Java \\& React}" in pre
    header = pre[pre.index("\\newcommand{\\resumeHeader}"):]
    assert header.index("Book Sam") < header.index("\\resumeHeadline") < header.index("\\end{center}")
    assert header.index("\\end{center}") < header.index("\\hrule")
    assert body == REAL_HEADER.split("\\begin{document}")[1]  # body untouched


def test_with_headline_without_center_appends_to_header():
    tex = render.with_headline(RESUME_TEX, "Software Engineer")
    pre = tex.split("\\begin{document}")[0]
    assert "\\resumeHeadline" in pre[pre.index("\\newcommand{\\resumeHeader}"):]
    assert "\\newcommand{\\resumeHeadline}{Software Engineer}" in pre


def _capturing_compiler(seen):
    fake = FakeCompiler()

    def compile_tex(work_dir, tex_name):
        seen[tex_name] = (work_dir / tex_name).read_text()
        return fake(work_dir, tex_name)

    return compile_tex


def test_build_tailored_renders_headline_only_when_set(latex_dir, tmp_path, fixtures_dir):
    doc = load_resume_doc(fixtures_dir / "resume")
    seen: dict[str, str] = {}
    kw = dict(job_title="Dev", company="Acme", contact_name=None, location="", today=date(2026, 10, 17))
    render.build_tailored(latex_dir, latex_dir / "sections" / "resume", doc, LETTER, tmp_path / "a",
                          _capturing_compiler(seen), **kw)
    assert seen["resume.tex"] == RESUME_TEX
    doc.headline = "Software Engineer · Java"
    render.build_tailored(latex_dir, latex_dir / "sections" / "resume", doc, LETTER, tmp_path / "b",
                          _capturing_compiler(seen), **kw)
    assert "Software Engineer · Java" in seen["resume.tex"]
    assert "resumeHeadline" not in seen["cover_letter.tex"]  # the letter header stays as it was
    assert (latex_dir / "resume.tex").read_text() == RESUME_TEX  # user's file untouched


@pytest.mark.skipif(shutil.which("tectonic") is None or not REAL_LATEX.is_dir(),
                    reason="needs tectonic and book-cv checked out")
def test_real_headline_compiles_under_name(tmp_path):
    import pypdfium2 as pdfium

    doc = load_resume_doc(REAL_LATEX / "sections" / "resume")
    doc.headline = "Full Stack Software Engineer · Java, Spring Boot, React"
    letter = CoverLetter(greeting="Dear Hiring Manager,", paragraphs=["I build React apps. " * 20] * 3)
    info = render.build_tailored(REAL_LATEX, REAL_LATEX / "sections" / "resume", doc, letter, tmp_path / "o",
                                 render.tectonic_compiler(shutil.which("tectonic")), job_title="Developer",
                                 company="Acme", contact_name=None, location="Adelaide SA",
                                 today=date(2026, 10, 17))
    pdf = pdfium.PdfDocument(str(tmp_path / "o" / "resume.pdf"))
    try:
        text = pdf[0].get_textpage().get_text_range()
    finally:
        pdf.close()
    assert "Full Stack Software Engineer" in text
    assert text.index("Book Sam") < text.index("Full Stack Software Engineer") < text.index("github.com")
    assert info["pages"]["resume"] <= 3


def test_with_headline_without_header_macro_goes_after_begin_document():
    plain = "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n"
    tex = render.with_headline(plain, "QA Engineer")
    assert tex.index("\\newcommand{\\resumeHeadline}{QA Engineer}") < tex.index("\\begin{document}")
    assert tex.index("\\begin{document}") < tex.index("\\resumeHeadline\\par") < tex.index("Hi")


def test_headline_dropped_when_it_adds_a_page(latex_dir, tmp_path, fixtures_dir):
    doc = load_resume_doc(fixtures_dir / "resume")
    doc.headline = "Software Engineer · Java"

    def compiler(work_dir, tex_name):
        pdf = work_dir / tex_name.replace(".tex", ".pdf")
        write_pdf(pdf, 3 if "resumeHeadline" in (work_dir / tex_name).read_text() else 2)
        return pdf

    kw = dict(job_title="Dev", company="Acme", contact_name=None, location="", today=date(2026, 10, 17))
    info = render.build_tailored(latex_dir, latex_dir / "sections" / "resume", doc, LETTER, tmp_path / "a",
                                 compiler, max_resume_pages=2, **kw)
    assert info["pages"]["resume"] == 2 and info["headline"] is None
    assert any("headline" in w.lower() for w in info["warnings"])
    info = render.build_tailored(latex_dir, latex_dir / "sections" / "resume", doc, LETTER, tmp_path / "b",
                                 compiler, max_resume_pages=3, **kw)
    assert info["pages"]["resume"] == 3 and info["headline"] == "Software Engineer · Java"
