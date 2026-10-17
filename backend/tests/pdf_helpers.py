"""Tiny real PDFs (via Pillow) and a fake compiler, so tailoring tests never need Tectonic."""

from pathlib import Path

from PIL import Image


def write_pdf(path: Path, pages: int = 1) -> None:
    imgs = [Image.new("RGB", (60, 85), "white") for _ in range(pages)]
    imgs[0].save(path, "PDF", save_all=True, append_images=imgs[1:])


def write_png(path: Path) -> None:
    Image.new("RGB", (6, 8), "white").save(path, "PNG")


class FakeCompiler:
    def __init__(self, pages: dict[str, int] | None = None, fail: str | None = None):
        self.calls: list[tuple[Path, str]] = []
        self.pages = pages or {}
        self.fail = fail

    def __call__(self, work_dir: Path, tex_name: str) -> Path:
        self.calls.append((work_dir, tex_name))
        if self.fail:
            from seekhunter.tailor.render import CompileError

            raise CompileError(self.fail)
        pdf = work_dir / tex_name.replace(".tex", ".pdf")
        write_pdf(pdf, self.pages.get(tex_name, 1))
        return pdf
