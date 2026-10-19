import json
from pathlib import Path

from seekhunter.models import Tailoring
from seekhunter.tailor.engine import JobContext, build_letter_prompt
from seekhunter.tailor.letter import mark_queued, run_letter_regen
from seekhunter.tailor.validate import AVAILABILITY
from tests.pdf_helpers import FakeCompiler
from tests.test_tailor_pipeline import _run, setup  # noqa: F401  (fixture)

NEW_PARAS = ["I would like to join Acme & Co as a React Developer. " * 4,
             "At Microsoft I built React apps with TypeScript. " * 6,
             f"{AVAILABILITY} I'd welcome a chat."]
LETTER = json.dumps({"greeting": "Dear Brayden,", "paragraphs": NEW_PARAS, "sign_off": "Kind regards,"})


def test_letter_prompt_is_short_specific_and_avoids_previous(fixtures_dir):
    from seekhunter.resume_doc import load_resume_doc
    from seekhunter.tailor.models import CoverLetter

    job = JobContext(title="Dev", company="A", location="", work_type="contract", contact_name="Jo Bloggs",
                     ad_text="ad")
    prompt = build_letter_prompt(job, load_resume_doc(fixtures_dir / "resume"),
                                 CoverLetter(greeting="Dear Jo,", paragraphs=["Old opening line."]))
    assert "130–200 words" in prompt and "exactly 3 short paragraphs" in prompt
    assert "48 hours per fortnight" in prompt and '"Dear Jo,"' in prompt
    assert "Old opening line." in prompt and "PREVIOUS LETTER" in prompt


def test_regenerates_only_the_letter(setup):  # noqa: F811
    env, session, job = setup
    t = _run(setup)
    resume_before = (Path(t.out_dir) / "resume.pdf").read_bytes()
    t.warnings = ["Kept the original bullet.", "Cover letter is 400 words (target 130–200)."]
    session.add(t)
    session.commit()
    mark_queued(session, t)
    prompts: list[str] = []
    compiler = FakeCompiler()
    t = run_letter_regen(session, t.id, env=env, llm=lambda p: prompts.append(p) or LETTER, compiler=compiler)
    regen = t.result["cover_letter_regen"]
    assert regen["status"] == "done" and regen["version"] == 1 and regen["error"] is None
    assert t.result["cover_letter"]["paragraphs"][2].startswith("I can work up to 48 hours")
    assert [name for _, name in compiler.calls] == ["cover_letter.tex"]
    assert (Path(t.out_dir) / "resume.pdf").read_bytes() == resume_before
    assert t.warnings[0] == "Kept the original bullet."
    assert not any("400 words" in w for w in t.warnings)
    assert not any("numbers not in your resume" in w for w in t.warnings)  # 48 is the visa limit
    assert "PREVIOUS LETTER" in prompts[0]


def test_failed_regen_keeps_previous_letter(setup):  # noqa: F811
    env, session, job = setup
    t = _run(setup)
    before = t.result["cover_letter"]
    t = run_letter_regen(session, t.id, env=env, llm=lambda p: "no json here", compiler=FakeCompiler())
    assert t.result["cover_letter_regen"]["status"] == "failed"
    assert "unusable" in t.result["cover_letter_regen"]["error"]
    assert session.get(Tailoring, t.id).result["cover_letter"] == before
