"""Cache of the untouched resume (PDF + PNG pages), keyed by the content hash of `latex/`.

Layout: `<data_dir>/resume_current/<hash>/{resume.pdf,resume-<n>.png,meta.json}`.
"""

import json
import os
import re
import shutil
from pathlib import Path

from seekhunter.models import utcnow
from seekhunter.tailor.render import Compiler, copy_latex, latex_hash, render_pages

_HASH = re.compile(r"^[0-9a-f]{8,64}$")


def current_root(data_dir: Path) -> Path:
    return data_dir / "resume_current"


def current_dir(data_dir: Path, resume_hash: str) -> Path:
    if not _HASH.match(resume_hash):
        raise ValueError("bad resume hash")
    return current_root(data_dir) / resume_hash


def read_current(data_dir: Path, resume_hash: str) -> dict | None:
    """Metadata of a cached build (`{"hash", "pages", "built_at"}`), or None if not built (or bad hash)."""
    try:
        d = current_dir(data_dir, resume_hash)
        meta = json.loads((d / "meta.json").read_text())
    except (ValueError, OSError):
        return None
    return meta if (d / "resume.pdf").exists() else None


def ensure_current(latex_dir: Path, data_dir: Path, compiler: Compiler) -> dict:
    """Build (once per hash) and return the cached preview of the current resume."""
    resume_hash = latex_hash(latex_dir)
    cached = read_current(data_dir, resume_hash)
    if cached:
        return cached
    final = current_dir(data_dir, resume_hash)
    tmp = final.with_name(f".{resume_hash}.tmp-{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        work = tmp / "work"
        copy_latex(latex_dir, work)
        shutil.move(compiler(work, "resume.tex"), tmp / "resume.pdf")
        shutil.rmtree(work)
        meta = {"hash": resume_hash, "pages": render_pages(tmp / "resume.pdf", tmp, "resume"),
                "built_at": utcnow().isoformat()}
        (tmp / "meta.json").write_text(json.dumps(meta))
        shutil.rmtree(final, ignore_errors=True)
        tmp.rename(final)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return meta
