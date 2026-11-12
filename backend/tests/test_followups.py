from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from seekhunter import followups, repo
from seekhunter.domain import JobData
from seekhunter.models import Interaction, Run, utcnow
from seekhunter.pipeline import run_follow_up_digest


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.ensure_seed(s)
        yield s


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


def _job(session, ext="1", company="Hays Recruitment", title="React Developer"):
    job, _ = repo.upsert_job(session, JobData(source="seek", external_id=ext, title=title, company=company,
                                              location="Adelaide SA", work_type="contract", url=f"u{ext}"))
    return job


def _applied(session, days, company="Acme", title="Dev", job_id=None):
    return repo.create_application(session, job_id=job_id, company=company, title=title,
                                   applied_at=utcnow() - timedelta(days=days))


def _contact(session, name="Brayden Mackay", company="Hays Recruitment", **kw):
    return repo.upsert_contact(session, name=name, company=company, role="Recruiter", **kw)


def _log(session, contact_id, kind, days_ago, application_id=None):
    return repo.create_interaction(session, contact_id=contact_id, application_id=application_id, kind=kind,
                                   at=utcnow() - timedelta(days=days_ago))


def kinds(items):
    return [(i.kind, i.company) for i in items]


# ------------------------------------------------------------------------------ application nudges


def test_applied_five_days_quiet_is_due_four_days_is_not(session):
    _applied(session, 5, company="Old")
    _applied(session, 4, company="Fresh")
    assert kinds(followups.due(session)) == [("application_nudge", "Old")]


def test_only_applied_stage_is_nudged(session):
    app = _applied(session, 9)
    repo.update_application(session, app, stage="interview")
    assert followups.due(session) == []


def test_stage_change_or_logged_contact_resets_the_clock(session):
    app = _applied(session, 9)
    job = _job(session)
    app.job_id = job.id
    session.add(app)
    session.commit()
    c = _contact(session)
    repo.link_contact_job(session, c.id, job.id)
    _log(session, c.id, "call", 2)
    assert followups.due(session) == []


def test_note_interactions_do_not_count_as_activity(session):
    app = _applied(session, 9)
    repo.create_interaction(session, application_id=app.id, kind="note", at=utcnow() - timedelta(days=1))
    assert kinds(followups.due(session)) == [("application_nudge", "Acme")]


def test_threshold_follows_settings(session):
    settings = repo.load_settings(session)
    settings.follow_up_days = 10
    repo.save_settings(session, settings)
    _applied(session, 9)
    assert followups.due(session) == []


def test_nudge_message_uses_contact_first_name_and_email_channel(session):
    job = _job(session, company="Acme")
    app = _applied(session, 6, company="Acme", title="React Developer", job_id=job.id)
    c = _contact(session, company="Acme", email="brayden@acme.com")
    repo.link_contact_job(session, c.id, job.id)
    item = followups.due(session)[0]
    assert item.application_id == app.id and item.job_id == job.id
    assert item.channel == "email" and item.contact_email == "brayden@acme.com"
    assert item.message.startswith("Hi Brayden,")
    assert "the React Developer role at Acme" in item.message
    assert item.subject == "Following up: React Developer"
    assert item.link == f"/?job={job.id}"


def test_agency_nudge_does_not_name_the_agency_as_employer(session):
    _applied(session, 6, company="Hays Recruitment", title="Java Dev")
    item = followups.due(session)[0]
    assert "the Java Dev role on" in item.message
    assert "at Hays" not in item.message
    assert item.message.startswith("Hi there,")


def test_long_silence_suggests_no_response(session):
    _applied(session, 35)
    assert "No response" in followups.due(session)[0].hint


# ---------------------------------------------------------------------------------------- linkedin


def test_linkedin_status_progression(session):
    c = _contact(session)
    assert followups.linkedin_statuses(session, [c.id]) == {}
    for kind, status in [("linkedin_invite", "sent"), ("linkedin_accepted", "accepted"),
                         ("linkedin_message", "messaged"), ("linkedin_reply", "replied")]:
        repo.create_interaction(session, contact_id=c.id, kind=kind)
        assert followups.linkedin_statuses(session, [c.id]) == {c.id: status}


def test_invite_pending_after_five_days(session):
    c = _contact(session, phone="0412 345 678")
    _log(session, c.id, "linkedin_invite", 6)
    (item,) = followups.due(session)
    assert item.kind == "linkedin_invite_pending"
    assert item.channel == "phone"
    assert item.contact_id == c.id
    assert item.link == f"/history?tab=contacts&contact={c.id}"


def test_invite_recent_or_followed_by_other_contact_is_not_due(session):
    c = _contact(session)
    _log(session, c.id, "linkedin_invite", 3)
    d = _contact(session, name="Jo Smith")
    _log(session, d.id, "linkedin_invite", 8)
    _log(session, d.id, "call", 1)
    assert followups.due(session) == []


def test_accepted_without_message_is_due_immediately(session):
    c = _contact(session)
    _log(session, c.id, "linkedin_invite", 3)
    _log(session, c.id, "linkedin_accepted", 0)
    (item,) = followups.due(session)
    assert item.kind == "linkedin_thank"
    assert item.message.startswith("Hi Brayden,\n\nThanks for connecting.")


def test_message_without_reply_after_five_days(session):
    c = _contact(session)
    _log(session, c.id, "linkedin_accepted", 9)
    _log(session, c.id, "linkedin_message", 6)
    assert kinds(followups.due(session)) == [("linkedin_no_reply", "Hays Recruitment")]
    _log(session, c.id, "linkedin_reply", 1)
    assert followups.due(session) == []


def test_linkedin_message_mentions_the_linked_job(session):
    c = _contact(session)
    job = _job(session, title="Full Stack Developer")
    repo.link_contact_job(session, c.id, job.id)
    _log(session, c.id, "linkedin_accepted", 0)
    item = followups.due(session)[0]
    assert "the Full Stack Developer role" in item.message
    assert item.job_id == job.id


# ----------------------------------------------------------------------------------------- actions


def test_snooze_hides_until_it_expires(session):
    _applied(session, 6)
    item = followups.due(session)[0]
    followups.snooze(session, item, 3)
    assert followups.due(session) == []
    assert followups.due(session, utcnow() + timedelta(days=4))  # snooze over


def test_dismiss_hides_this_occurrence_only(session):
    app = _applied(session, 6)
    followups.dismiss(session, followups.due(session)[0])
    assert followups.due(session) == []
    # A later stage bounce starts a new cycle with a new key; it is due again after the quiet period.
    repo.update_application(session, app, stage="screening")
    repo.update_application(session, app, stage="applied")
    later = utcnow() + timedelta(days=6)
    assert kinds(followups.due(session, later)) == [("application_nudge", "Acme")]


def test_done_logs_the_interaction_and_restarts_the_cycle(session):
    job = _job(session, company="Acme")
    app = _applied(session, 6, company="Acme", job_id=job.id)
    c = _contact(session, company="Acme", email="b@acme.com")
    repo.link_contact_job(session, c.id, job.id)
    item = followups.due(session)[0]
    interaction = followups.mark_done(session, item, "sent the email")
    assert interaction.kind == "email"
    assert interaction.application_id == app.id and interaction.contact_id == c.id
    assert interaction.note == "sent the email"
    assert followups.due(session) == []
    later = utcnow() + timedelta(days=5, minutes=1)
    assert kinds(followups.due(session, later)) == [("application_nudge", "Acme")]


def test_done_on_linkedin_thank_logs_a_message(session):
    c = _contact(session)
    _log(session, c.id, "linkedin_accepted", 0)
    followups.mark_done(session, followups.due(session)[0])
    kinds_logged = [i.kind for i in session.exec(select(Interaction)).all()]
    assert kinds_logged == ["linkedin_accepted", "linkedin_message"]
    assert followups.due(session) == []


# ------------------------------------------------------------------------------------------ digest


def test_format_digest_none_when_nothing_due():
    assert followups.format_digest([], "Thu 12 Nov", "https://sh") is None


def test_format_digest_lists_items_with_deep_links(session):
    job = _job(session, company="Acme", title="React Developer")
    _applied(session, 6, company="Acme", title="React Developer", job_id=job.id)
    c = _contact(session, phone="08 8216 3534")
    _log(session, c.id, "linkedin_accepted", 0)
    base = "https://seekhunter.bookmountain.work"
    text = followups.format_digest(followups.due(session), "Thu 12 Nov", base)
    lines = text.splitlines()
    assert lines[0] == "SeekHunter follow-ups · Thu 12 Nov"
    assert lines[1] == "2 due"
    assert lines[3] == "1. Say thanks · Hays Recruitment · accepted your invite"
    assert "   Brayden Mackay · 08 8216 3534 (linkedin)" in lines
    assert "2. Nudge · Acme · React Developer · applied, quiet 6d" in lines
    assert f"   https://seekhunter.bookmountain.work/?job={job.id}" in lines
    assert lines[-1] == "Messages ready to copy: https://seekhunter.bookmountain.work/history?tab=followups"


def test_format_digest_caps_items(session):
    for n in range(followups.DIGEST_MAX_ITEMS + 2):
        _applied(session, 6, company=f"C{n:02d}")
    text = followups.format_digest(followups.due(session), "Thu", "https://sh")
    assert text.splitlines()[-3] == "+2 more"


def test_run_digest_skips_sending_when_nothing_due(session):
    n = FakeNotifier()
    assert run_follow_up_digest(session, n, "https://sh") == 0
    assert n.sent == []


def test_run_digest_sends_and_records_run(session):
    _applied(session, 7)
    n = FakeNotifier()
    assert run_follow_up_digest(session, n, "seekhunter.bookmountain.work") == 1
    assert len(n.sent) == 1 and "1. Nudge · Acme · Dev" in n.sent[0]
    assert "https://seekhunter.bookmountain.work/history?tab=followups" in n.sent[0]
    assert session.exec(select(Run).where(Run.kind == "follow_ups")).one().notified == 1


def test_run_digest_respects_setting(session):
    settings = repo.load_settings(session)
    settings.follow_up_digest_enabled = False
    repo.save_settings(session, settings)
    _applied(session, 7)
    n = FakeNotifier()
    run_follow_up_digest(session, n, "https://sh")
    assert n.sent == []


def test_format_text_includes_messages_and_keys(session):
    _applied(session, 6)
    text = followups.format_text(followups.due(session), utcnow())
    assert text.startswith("Follow-ups due: 1")
    assert "key: application_nudge-" in text
    assert "message:\nHi there," in text
    assert followups.format_text([], utcnow()) == "No follow-ups due."
