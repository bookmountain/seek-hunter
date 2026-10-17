"""Human-facing diff between the base resume and a tailored one (for the website's Changes panel).

Computed on read from the stored base/tailored docs, so trivial rewrites (spelling variants,
punctuation) in older runs also show as kept/moved.
"""

from seekhunter.resume_doc import ResumeDoc
from seekhunter.tailor.textdiff import is_trivial_change, word_diff

__all__ = ["change_counts", "compute_changes", "word_diff"]


def _bullet_changes(base: ResumeDoc, tailored: ResumeDoc) -> list[dict]:
    changes: list[dict] = []
    for exp in base.experiences:
        after_exp = tailored.experience(exp.id)
        after_bullets = after_exp.bullets if after_exp else []
        after_text = {b.id: b.text for b in after_bullets}
        after_pos = {b.id: n for n, b in enumerate(after_bullets)}
        # "moved" compares relative order among surviving bullets, so a removal doesn't flag
        # every bullet after it as moved.
        survivors = [b.id for b in exp.bullets if b.id in after_pos]
        rank_before = {bid: n for n, bid in enumerate(survivors)}
        rank_after = {bid: n for n, bid in enumerate(sorted(survivors, key=after_pos.__getitem__))}
        for pos, b in enumerate(exp.bullets):
            new = after_text.get(b.id)
            entry = {"type": "bullet", "experience": exp.id, "company": exp.company, "id": b.id,
                     "before": b.text, "after": new, "position_before": pos,
                     "position_after": after_pos.get(b.id)}
            if new is None:
                entry["status"] = "removed"
            elif new != b.text and not is_trivial_change(b.text, new):
                entry["status"] = "reworded"
                entry["diff"] = word_diff(b.text, new)
            else:
                entry["status"] = "moved" if rank_before[b.id] != rank_after[b.id] else "kept"
            changes.append(entry)
    return changes


def compute_changes(base: ResumeDoc, tailored: ResumeDoc) -> list[dict]:
    summary_changed = base.summary != tailored.summary and not is_trivial_change(base.summary,
                                                                                 tailored.summary)
    summary = {"type": "summary", "before": base.summary, "after": tailored.summary,
               "changed": summary_changed}
    if summary_changed:
        summary["diff"] = word_diff(base.summary, tailored.summary)
    changes: list[dict] = []
    if tailored.headline and tailored.headline != base.headline:
        changes.append({"type": "headline", "after": tailored.headline})
    changes += [summary, *_bullet_changes(base, tailored)]

    after_skills = {s.id: s for s in tailored.skills}
    for s in base.skills:
        new = after_skills.get(s.id)
        after_items = list(new.items) if new else []
        changes.append({"type": "skills", "id": s.id, "category": s.category, "before": list(s.items),
                        "after": after_items, "changed": after_items != list(s.items)})

    included = {p.id for p in tailored.projects}
    changes.append({"type": "projects", "included": [p.name for p in tailored.projects],
                    "excluded": [p.name for p in base.projects if p.id not in included],
                    "changed": [p.id for p in tailored.projects] != [p.id for p in base.projects]})
    return changes


def change_counts(changes: list[dict]) -> dict:
    """Top-level tally for the Changes panel header. `projects_changed` is true when the included
    project list differs from the base list (membership or order)."""
    bullets = [c["status"] for c in changes if c["type"] == "bullet"]
    summary = next((c for c in changes if c["type"] == "summary"), None)
    projects = next((c for c in changes if c["type"] == "projects"), None)
    return {
        "reworded": bullets.count("reworded"),
        "removed": bullets.count("removed"),
        "moved": bullets.count("moved"),
        "skills_reordered": sum(1 for c in changes if c["type"] == "skills" and c["changed"]),
        "projects_changed": bool(projects and projects.get("changed")),
        "summary_changed": bool(summary and summary["changed"]),
        "headline_added": any(c["type"] == "headline" for c in changes),
    }
