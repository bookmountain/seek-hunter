from seekhunter.resume_doc import Bullet, Experience, Project, ResumeDoc, SkillLine
from seekhunter.tailor.changes import change_counts, compute_changes, word_diff
from seekhunter.tailor.textdiff import is_trivial_change


def _doc(summary="Built things.", bullets=("a one", "b two", "c three"), skills=("X", "Y"),
         projects=("p1", "p2")) -> ResumeDoc:
    return ResumeDoc(
        summary=summary,
        skills=[SkillLine(id="lang", category="Languages", items=list(skills))],
        experiences=[Experience(id="ms", title="t", company="MS", location="", dates="",
                                bullets=[Bullet(id=f"ms-b{i}", text=t) for i, t in enumerate(bullets)])],
        projects=[Project(id=p, name=p.upper(), stack="", bullets=[]) for p in projects])


def _bullets(changes):
    return {c["id"]: c for c in changes if c["type"] == "bullet"}


def test_trivial_change_detection():
    assert is_trivial_change("Optimizing the labeling flow.", "Optimising the labelling flow")
    assert is_trivial_change("Color at the center", "colour at the centre")
    assert is_trivial_change("Built real-time apps", "Built real time apps")
    assert is_trivial_change("same", "same")
    assert not is_trivial_change("Built React UI", "Built Angular UI")
    assert not is_trivial_change("Built the UI", "Built UI")
    assert not is_trivial_change("Led a team", "Led the team")  # short words aren't spelling variants


def test_word_diff_one_word_change():
    assert word_diff("Built the React UI.", "Built the Angular UI.") == [
        {"op": "equal", "text": "Built the"}, {"op": "delete", "text": "React"},
        {"op": "insert", "text": "Angular"}, {"op": "equal", "text": "UI."}]
    assert word_diff("a b", "a b c") == [{"op": "equal", "text": "a b"}, {"op": "insert", "text": "c"}]


def test_moved_with_positions_and_counts():
    base = _doc()
    tailored = base.model_copy(deep=True)
    b0, b1, b2 = tailored.experiences[0].bullets
    b1 = b1.model_copy(update={"text": "b two rewritten with Jest"})
    tailored.experiences[0].bullets = [b2, b0]  # b1 removed, c moved to front
    tailored.experiences[0].bullets.insert(1, b1)
    tailored.summary = "Shipped things."
    tailored.skills[0].items = ["Y", "X"]
    tailored.projects = tailored.projects[:1]
    changes = compute_changes(base, tailored)
    by = _bullets(changes)
    b2 = by["ms-b2"]
    assert (b2["status"], b2["position_before"], b2["position_after"]) == ("moved", 2, 0)
    assert by["ms-b1"]["status"] == "reworded" and by["ms-b1"]["position_after"] == 1
    assert by["ms-b1"]["diff"] == [{"op": "equal", "text": "b two"},
                                   {"op": "insert", "text": "rewritten with Jest"}]
    assert by["ms-b0"]["status"] == "moved" and by["ms-b0"]["position_after"] == 2
    assert changes[0]["changed"] and changes[0]["diff"] == [
        {"op": "delete", "text": "Built"}, {"op": "insert", "text": "Shipped"},
        {"op": "equal", "text": "things."}]
    assert change_counts(changes) == {"reworded": 1, "removed": 0, "moved": 2, "skills_reordered": 1,
                                      "projects_changed": True, "summary_changed": True,
                                      "headline_added": False}


def test_removed_does_not_mark_followers_moved():
    base = _doc()
    tailored = base.model_copy(deep=True)
    tailored.experiences[0].bullets = tailored.experiences[0].bullets[1:]
    by = _bullets(compute_changes(base, tailored))
    assert by["ms-b0"]["status"] == "removed" and by["ms-b0"]["position_after"] is None
    b1 = by["ms-b1"]
    assert (b1["status"], b1["position_before"], b1["position_after"]) == ("kept", 1, 0)
    assert "diff" not in by["ms-b1"]


def test_old_run_with_spelling_only_change_shows_kept():
    base = _doc(summary="Optimizing the organization.", bullets=("Built labeling tools.", "b two"))
    tailored = base.model_copy(deep=True)
    tailored.summary = "Optimising the organisation."
    tailored.experiences[0].bullets[0].text = "Built labelling tools."
    tailored.experiences[0].bullets.reverse()
    changes = compute_changes(base, tailored)
    assert changes[0]["changed"] is False and "diff" not in changes[0]
    by = _bullets(changes)
    assert by["ms-b0"]["status"] == "moved" and "diff" not in by["ms-b0"]
    counts = change_counts(changes)
    assert counts["reworded"] == 0 and counts["summary_changed"] is False and counts["moved"] == 2
    assert counts["projects_changed"] is False and counts["skills_reordered"] == 0


def test_headline_change_first_and_counted():
    base = _doc()
    tailored = base.model_copy(update={"headline": "Software Engineer · Java"})
    changes = compute_changes(base, tailored)
    assert changes[0] == {"type": "headline", "after": "Software Engineer · Java"}
    assert change_counts(changes)["headline_added"] is True
    plain = compute_changes(base, base)
    assert all(c["type"] != "headline" for c in plain)
    assert change_counts(plain)["headline_added"] is False
