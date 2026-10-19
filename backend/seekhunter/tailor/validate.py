"""Guard rails between the LLM's suggested edits and the rendered resume.

Anything that could add a fact (a skill, a number, a technology, an unknown id) is reverted to the
original text with a human-readable warning; the result can only reorder, trim, or reword.
Rewrites that only change spelling variants or punctuation are silently reverted (no tailoring value).
"""

import re
from dataclasses import dataclass, field

from seekhunter.resume_doc import Bullet, ResumeDoc
from seekhunter.skills import extract_skills
from seekhunter.tailor.headline import validate_headline
from seekhunter.tailor.models import CoverLetter, TailorOutput
from seekhunter.tailor.phrases import mentions
from seekhunter.tailor.textdiff import is_trivial_change

SUMMARY_MAX = 480
MIN_BULLETS_RECENT = 2
RECENT_ROLES = 2
LETTER_WORDS = (130, 200)
LETTER_PARAGRAPHS = (3, 3)
LIST_CAP = 20
# Student-visa work limits, quoted in letters for part-time/contract/casual roles.
AVAILABILITY = ("I can work up to 48 hours per fortnight during study periods and full-time during "
                "university holidays.")


@dataclass
class Validated:
    doc: ResumeDoc
    cover_letter: CoverLetter
    keywords_matched: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    supported_phrases: list[str] = field(default_factory=list)
    unsupported_phrases: list[str] = field(default_factory=list)


def numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d+(?:[.,]\d+)*", text)}


def _clip(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _clean_list(values: list[str]) -> list[str]:
    seen, out = set(), []
    for v in values:
        v = " ".join(str(v).split())[:80]
        if v and v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)
    return out[:LIST_CAP]


def _new_facts(text: str, allowed_numbers: set[str], known_skills: set[str], original: str = "",
               unsupported: tuple[str, ...] = ()) -> list[str]:
    """Numbers / skill-vocabulary terms in `text` that the allowed sets don't cover, plus UNSUPPORTED
    target phrases that `text` mentions but `original` didn't."""
    issues = sorted(numbers(text) - allowed_numbers)
    issues += sorted(extract_skills(text) - known_skills)
    issues += [p for p in unsupported if mentions(p, text) and not mentions(p, original)
               and p not in issues]
    return issues


def _validate_summary(base: ResumeDoc, summary: str, corpus_numbers: set[str], known: set[str],
                      warnings: list[str], unsupported: tuple[str, ...] = ()) -> str:
    summary = " ".join(summary.split())
    if not summary:
        return base.summary
    if len(summary) > max(SUMMARY_MAX, len(base.summary)):
        warnings.append(f"Summary was too long ({len(summary)} chars); kept the original summary.")
        return base.summary
    issues = _new_facts(summary, corpus_numbers, known, base.corpus(), unsupported)
    if issues:
        warnings.append(f"Summary added {', '.join(issues)} (not in your resume); kept the original summary.")
        return base.summary
    if is_trivial_change(base.summary, summary):
        return base.summary
    return summary


def _validate_skills(base: ResumeDoc, out: TailorOutput, warnings: list[str]) -> list:
    by_id = {s.id: s for s in base.skills}
    lines, used = [], set()
    for edit in out.skills:
        line = by_id.get(edit.id)
        if line is None:
            warnings.append(f"Ignored unknown skill line '{edit.id}'.")
            continue
        if edit.id in used:
            continue
        used.add(edit.id)
        originals = {i.casefold(): i for i in line.items}
        items, seen = [], set()
        for raw in edit.items:
            key = " ".join(str(raw).split()).casefold()
            if key in originals and key not in seen:
                seen.add(key)
                items.append(originals[key])
            elif key not in originals and key:
                warnings.append(
                    f"Skills · {line.category}: dropped '{_clip(str(raw), 40)}' (not in your resume).")
        lines.append(line.model_copy(update={"items": items or list(line.items)}))
    lines += [s.model_copy() for s in base.skills if s.id not in used]
    return lines


def _validate_experiences(base: ResumeDoc, out: TailorOutput, known: set[str],
                          warnings: list[str], unsupported: tuple[str, ...] = ()) -> list:
    base_ids = {e.id for e in base.experiences}
    edits: dict[str, list] = {}
    for edit in out.experiences:
        if edit.id not in base_ids:
            warnings.append(f"Ignored unknown role '{edit.id}'.")
        elif edit.id not in edits:
            edits[edit.id] = edit.bullets

    experiences = []
    for idx, exp in enumerate(base.experiences):
        bullet_edits = edits.get(exp.id)
        if not bullet_edits:
            experiences.append(exp.model_copy(deep=True))
            continue
        originals = {b.id: b for b in exp.bullets}
        kept: list[Bullet] = []
        for be in bullet_edits:
            orig = originals.get(be.id)
            if orig is None:
                warnings.append(f"{exp.company}: ignored unknown bullet '{be.id}'.")
                continue
            if any(b.id == be.id for b in kept):
                continue
            text = " ".join(be.text.split())
            if not text:
                kept.append(orig.model_copy())
                continue
            issues = _new_facts(text, numbers(orig.text), known, orig.text, unsupported)
            if issues:
                warnings.append(f"{exp.company}: kept original wording of '{_clip(orig.text)}' "
                                f"(rewrite added {', '.join(issues)}).")
                kept.append(orig.model_copy())
            elif is_trivial_change(orig.text, text):
                kept.append(orig.model_copy())  # spelling/punctuation only: keep the candidate's wording
            else:
                kept.append(Bullet(id=be.id, text=text))
        if not kept:
            kept = [b.model_copy() for b in exp.bullets]
        if idx < RECENT_ROLES:
            need = min(MIN_BULLETS_RECENT, len(exp.bullets))
            if len(kept) < need:
                for b in exp.bullets:
                    if len(kept) >= need:
                        break
                    if all(k.id != b.id for k in kept):
                        kept.append(b.model_copy())
                order = {b.id: n for n, b in enumerate(exp.bullets)}
                kept.sort(key=lambda b: order[b.id])
                warnings.append(f"{exp.company}: restored bullets to keep at least {need} for a recent role.")
        experiences.append(exp.model_copy(update={"bullets": kept}))
    return experiences


def _validate_projects(base: ResumeDoc, out: TailorOutput, warnings: list[str]) -> list:
    if out.projects is None:
        return [p.model_copy(deep=True) for p in base.projects]
    by_id = {p.id: p for p in base.projects}
    chosen, seen = [], set()
    for pid in out.projects:
        if pid not in by_id:
            warnings.append(f"Ignored unknown project '{pid}'.")
        elif pid not in seen:
            seen.add(pid)
            chosen.append(by_id[pid].model_copy(deep=True))
    if not chosen:
        if base.projects:
            warnings.append("No projects were selected; kept all projects.")
        return [p.model_copy(deep=True) for p in base.projects]
    return chosen


def validate_letter_only(base: ResumeDoc, letter: CoverLetter, *, contact_name: str | None = None,
                         supported: list[str] | tuple[str, ...] = ()) -> tuple[CoverLetter, list[str]]:
    """A regenerated cover letter checked against `base` (the tailored resume): (letter, warnings)."""
    warnings: list[str] = []
    corpus = base.corpus() + "\n" + base.education_tex
    known = extract_skills(corpus) | extract_skills("\n".join(supported))
    return _validate_letter(letter, contact_name, numbers(corpus), known, warnings), warnings


def _validate_letter(letter: CoverLetter, contact_name: str | None, corpus_numbers: set[str],
                     known: set[str], warnings: list[str]) -> CoverLetter:
    paragraphs = [" ".join(p.split()) for p in letter.paragraphs if p and p.strip()]
    if not paragraphs:
        raise ValueError("model returned no cover letter paragraphs")
    greeting = " ".join(letter.greeting.split())
    first = (contact_name or "").split()[0] if (contact_name or "").strip() else ""
    if first:
        if first.casefold() not in greeting.casefold():
            greeting = f"Dear {first},"
    elif greeting != "Dear Hiring Manager,":
        greeting = "Dear Hiring Manager,"
    sign_off = " ".join(letter.sign_off.split()) or "Kind regards,"
    result = CoverLetter(greeting=greeting, paragraphs=paragraphs, sign_off=sign_off)

    words = result.word_count()
    if not LETTER_WORDS[0] <= words <= LETTER_WORDS[1]:
        warnings.append(f"Cover letter is {words} words (target {LETTER_WORDS[0]}–{LETTER_WORDS[1]}).")
    if not LETTER_PARAGRAPHS[0] <= len(paragraphs) <= LETTER_PARAGRAPHS[1]:
        warnings.append(f"Cover letter has {len(paragraphs)} paragraphs (target {LETTER_PARAGRAPHS[1]}).")
    body = " ".join(paragraphs)
    unknown_skills = sorted(extract_skills(body) - known)
    if unknown_skills:
        warnings.append(f"Cover letter mentions {', '.join(unknown_skills)}, which isn't in your resume; "
                        "check the wording before sending.")
    new_numbers = sorted(numbers(body) - corpus_numbers - numbers(AVAILABILITY))
    if new_numbers:
        warnings.append(f"Cover letter uses numbers not in your resume ({', '.join(new_numbers)}); "
                        "check them before sending.")
    return result


def validate(base: ResumeDoc, out: TailorOutput, *, contact_name: str | None = None, job_title: str = "",
             ad_text: str = "", supported: list[str] | tuple[str, ...] = (),
             unsupported: list[str] | tuple[str, ...] = ()) -> Validated:
    """`supported` target phrases (backed by the resume, see `phrases.annotate`) may appear in rewritten
    text even when their skills aren't spelled out in the resume; `unsupported` ones are rejected."""
    warnings: list[str] = []
    corpus = base.corpus() + "\n" + base.education_tex
    known = extract_skills(corpus) | extract_skills("\n".join(supported))
    corpus_numbers = numbers(corpus)
    banned = tuple(unsupported)
    headline, headline_warning = validate_headline(out.headline, base, job_title=job_title, ad_text=ad_text,
                                                   supported=list(supported))
    if headline_warning:
        warnings.append(headline_warning)
    doc = base.model_copy(update={
        "headline": headline,
        "summary": _validate_summary(base, out.summary, corpus_numbers, known, warnings, banned),
        "skills": _validate_skills(base, out, warnings),
        "experiences": _validate_experiences(base, out, known, warnings, banned),
        "projects": _validate_projects(base, out, warnings),
    })
    letter = _validate_letter(out.cover_letter, contact_name, corpus_numbers, known, warnings)
    return Validated(doc=doc, cover_letter=letter, keywords_matched=_clean_list(out.keywords_matched),
                     gaps=_clean_list(out.gaps), warnings=warnings, supported_phrases=list(supported),
                     unsupported_phrases=list(unsupported))
