"""Human-facing diff between the base resume and a tailored one (for the website's Changes panel)."""

from seekhunter.resume_doc import ResumeDoc


def compute_changes(base: ResumeDoc, tailored: ResumeDoc) -> list[dict]:
    changes: list[dict] = [{"type": "summary", "before": base.summary, "after": tailored.summary,
                            "changed": base.summary != tailored.summary}]

    for exp in base.experiences:
        after_exp = tailored.experience(exp.id)
        after = {b.id: b.text for b in after_exp.bullets} if after_exp else {}
        for b in exp.bullets:
            new = after.get(b.id)
            status = "removed" if new is None else "kept" if new == b.text else "reworded"
            changes.append({"type": "bullet", "experience": exp.id, "company": exp.company, "id": b.id,
                            "status": status, "before": b.text, "after": new})

    after_skills = {s.id: s for s in tailored.skills}
    for s in base.skills:
        new = after_skills.get(s.id)
        after_items = list(new.items) if new else []
        changes.append({"type": "skills", "id": s.id, "category": s.category, "before": list(s.items),
                        "after": after_items, "changed": after_items != list(s.items)})

    included = {p.id for p in tailored.projects}
    changes.append({"type": "projects", "included": [p.name for p in tailored.projects],
                    "excluded": [p.name for p in base.projects if p.id not in included]})
    return changes
