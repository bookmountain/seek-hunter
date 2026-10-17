from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import repo
from seekhunter.domain import JobData, company_key
from seekhunter.models import utcnow


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def data(ext="1", source="seek", title="Dev", company="Acme"):
    return JobData(source=source, external_id=ext, title=title, company=company, location="Adelaide SA",
                   work_type="part_time", url=f"https://x/{ext}")


# ---------------------------------------------------------------------------- applications


def test_create_application_also_writes_created_event(session):
    app = repo.create_application(session, job_id=None, company="Acme Pty Ltd", title="Dev",
                                  applied_at=utcnow())
    assert app.company_key == company_key("Acme Pty Ltd")
    events = repo.history_timeline(session)
    assert len(events) == 1
    assert events[0]["kind"] == "created" and events[0]["to_stage"] == "applied"


def test_ensure_application_for_job_is_idempotent(session):
    job, _ = repo.upsert_job(session, data())
    app1 = repo.ensure_application_for_job(session, job, utcnow())
    app2 = repo.ensure_application_for_job(session, job, utcnow())
    assert app1.id == app2.id
    assert len(repo.list_applications(session)) == 1


def test_ensure_application_for_job_attaches_latest_done_tailoring(session):
    job, _ = repo.upsert_job(session, data())
    t1 = repo.create_tailoring(session, job.id)
    t1.status = "done"
    repo.save_tailoring(session, t1)
    t2 = repo.create_tailoring(session, job.id)
    t2.status = "done"
    repo.save_tailoring(session, t2)
    queued = repo.create_tailoring(session, job.id)  # not done: should be ignored

    app = repo.ensure_application_for_job(session, job, utcnow())
    assert app.tailoring_id == t2.id
    assert queued.status == "queued"


def test_update_application_records_stage_changed_event(session):
    app = repo.create_application(session, job_id=None, company="Acme", title="Dev", applied_at=utcnow())
    repo.update_application(session, app, stage="interview")
    session.refresh(app)
    assert app.stage == "interview"
    events = [e for e in repo.history_timeline(session) if e["kind"] == "stage_changed"]
    assert events[0]["from_stage"] == "applied" and events[0]["to_stage"] == "interview"


def test_update_application_no_event_when_stage_unchanged(session):
    app = repo.create_application(session, job_id=None, company="Acme", title="Dev", applied_at=utcnow())
    repo.update_application(session, app, notes="called them")
    session.refresh(app)
    assert app.notes == "called them"
    kinds = [e["kind"] for e in repo.history_timeline(session)]
    assert kinds == ["created"]


def test_delete_application_detaches_interactions_instead_of_deleting_them(session):
    app = repo.create_application(session, job_id=None, company="Acme", title="Dev", applied_at=utcnow())
    interaction = repo.create_interaction(session, application_id=app.id, kind="note", note="x")
    repo.delete_application(session, app)
    session.refresh(interaction)
    assert interaction.application_id is None
    assert repo.list_applications(session) == []


def test_list_applications_filters_by_stage_and_query(session):
    repo.create_application(session, job_id=None, company="Acme", title="Dev", applied_at=utcnow())
    other = repo.create_application(session, job_id=None, company="Other", title="QA", applied_at=utcnow())
    repo.update_application(session, other, stage="interview")

    assert len(repo.list_applications(session, stage="interview")) == 1
    assert [a.title for a in repo.list_applications(session, q="qa")] == ["QA"]


def test_applications_by_company_keys_batches_and_orders_newest_first(session):
    now = utcnow()
    repo.create_application(session, job_id=None, company="Acme", title="Old",
                            applied_at=now - timedelta(days=5))
    repo.create_application(session, job_id=None, company="Acme Pty Ltd", title="New", applied_at=now)
    repo.create_application(session, job_id=None, company="Other", title="Z", applied_at=now)

    out = repo.applications_by_company_keys(session, {company_key("Acme")})
    assert [a.title for a in out[company_key("Acme")]] == ["New", "Old"]


def test_applications_by_company_keys_empty_set_returns_empty_dict(session):
    assert repo.applications_by_company_keys(session, set()) == {}


def test_applications_by_job_ids(session):
    job, _ = repo.upsert_job(session, data())
    app = repo.ensure_application_for_job(session, job, utcnow())
    out = repo.applications_by_job_ids(session, [job.id])
    assert out == {job.id: app}
    assert repo.applications_by_job_ids(session, []) == {}


def test_follow_ups_due_only_applied_stage_older_than_7_days_with_no_activity(session):
    now = utcnow()
    stale = repo.create_application(session, job_id=None, company="Acme", title="Stale",
                                     applied_at=now - timedelta(days=9))
    recent = repo.create_application(session, job_id=None, company="Other", title="Recent",
                                      applied_at=now - timedelta(days=2))
    contacted = repo.create_application(session, job_id=None, company="Third", title="Contacted",
                                        applied_at=now - timedelta(days=10))
    repo.create_interaction(session, application_id=contacted.id, kind="call",
                            at=now - timedelta(days=1))
    in_interview = repo.create_application(session, job_id=None, company="Fourth", title="Interviewing",
                                           applied_at=now - timedelta(days=10))
    repo.update_application(session, in_interview, stage="interview")

    due = repo.follow_ups_due(session, now)
    assert [a.id for a in due] == [stale.id]
    assert recent.id not in [a.id for a in due]


def test_stage_counts(session):
    a = repo.create_application(session, job_id=None, company="Acme", title="A", applied_at=utcnow())
    repo.create_application(session, job_id=None, company="B", title="B", applied_at=utcnow())
    repo.update_application(session, a, stage="interview")
    assert repo.stage_counts(session) == {"applied": 1, "interview": 1}


def test_recent_applications_filters_by_since(session):
    now = utcnow()
    repo.create_application(session, job_id=None, company="Old", title="Old",
                            applied_at=now - timedelta(days=30))
    recent = repo.create_application(session, job_id=None, company="New", title="New", applied_at=now)
    out = repo.recent_applications(session, now - timedelta(days=1))
    assert [a.id for a in out] == [recent.id]


# ---------------------------------------------------------------------------- contacts


def test_upsert_contact_creates_then_merges_missing_fields(session):
    c1 = repo.upsert_contact(session, name="Brayden Mackay", company="Acme Pty Ltd", phone="08 8216 3534")
    c2 = repo.upsert_contact(session, name="brayden mackay", company="ACME", email="b@acme.com",
                             linkedin="https://linkedin.com/in/b")
    assert c1.id == c2.id
    session.refresh(c1)
    assert c1.phone == "08 8216 3534"
    assert c1.email == "b@acme.com"
    assert c1.linkedin == "https://linkedin.com/in/b"


def test_upsert_contact_does_not_overwrite_existing_fields(session):
    repo.upsert_contact(session, name="Jane Doe", company="Acme", phone="0412 345 678")
    c2 = repo.upsert_contact(session, name="Jane Doe", company="Acme", phone="0499 999 999")
    assert c2.phone == "0412 345 678"


def test_upsert_contact_distinguishes_same_name_different_company(session):
    c1 = repo.upsert_contact(session, name="Jane Doe", company="Acme")
    c2 = repo.upsert_contact(session, name="Jane Doe", company="Other Co")
    assert c1.id != c2.id


def test_link_contact_job_is_idempotent(session):
    job, _ = repo.upsert_job(session, data())
    contact = repo.upsert_contact(session, name="Jane Doe", company="Acme")
    repo.link_contact_job(session, contact.id, job.id)
    repo.link_contact_job(session, contact.id, job.id)
    assert len(repo.jobs_for_contact(session, contact.id)) == 1


def test_contact_stats_counts_interactions_jobs_and_applications(session):
    job, _ = repo.upsert_job(session, data())
    contact = repo.upsert_contact(session, name="Jane Doe", company="Acme")
    repo.link_contact_job(session, contact.id, job.id)
    repo.ensure_application_for_job(session, job, utcnow())
    repo.create_interaction(session, contact_id=contact.id, kind="call", note="rang")

    stats = repo.contact_stats(session, contact.id)
    assert stats["interaction_count"] == 1
    assert stats["job_count"] == 1
    assert stats["application_count"] == 1
    assert stats["last_interaction"] is not None


def test_list_contacts_filters_by_query(session):
    repo.upsert_contact(session, name="Jane Doe", company="Acme")
    repo.upsert_contact(session, name="Sam Lee", company="Other")
    assert [c.name for c in repo.list_contacts(session, q="jane")] == ["Jane Doe"]


def test_applications_for_contact_via_linked_jobs(session):
    job, _ = repo.upsert_job(session, data())
    contact = repo.upsert_contact(session, name="Jane Doe", company="Acme")
    repo.link_contact_job(session, contact.id, job.id)
    app = repo.ensure_application_for_job(session, job, utcnow())
    assert [a.id for a in repo.applications_for_contact(session, contact.id)] == [app.id]


def test_create_and_delete_interaction(session):
    contact = repo.upsert_contact(session, name="Jane Doe", company="Acme")
    interaction = repo.create_interaction(session, contact_id=contact.id, kind="call")
    assert repo.interactions_for_contact(session, contact.id) == [interaction]
    repo.delete_interaction(session, interaction)
    assert repo.interactions_for_contact(session, contact.id) == []


# ---------------------------------------------------------------------------- companies + timeline


def test_list_companies_groups_by_company_key_sorted_by_last_applied(session):
    now = utcnow()
    repo.create_application(session, job_id=None, company="Acme", title="Old",
                            applied_at=now - timedelta(days=5))
    repo.create_application(session, job_id=None, company="Acme Pty Ltd", title="New", applied_at=now)
    repo.create_application(session, job_id=None, company="Zeta", title="Z", applied_at=now - timedelta(1))
    repo.upsert_contact(session, name="Jane Doe", company="Acme")

    companies = repo.list_companies(session)
    assert [c["company_key"] for c in companies] == [company_key("Acme"), company_key("Zeta")]
    acme = companies[0]
    assert acme["application_count"] == 2
    assert [a["title"] for a in acme["applications"]] == ["New", "Old"]
    assert acme["contacts"] == [{"id": 1, "name": "Jane Doe"}]


def test_history_timeline_merges_events_and_interactions_newest_first(session):
    now = utcnow()
    app = repo.create_application(session, job_id=None, company="Acme", title="Dev",
                                  applied_at=now - timedelta(days=2))
    contact = repo.upsert_contact(session, name="Jane Doe", company="Acme")
    repo.create_interaction(session, contact_id=contact.id, application_id=app.id, kind="call",
                            at=now - timedelta(days=1), note="rang")
    repo.update_application(session, app, stage="interview")

    timeline = repo.history_timeline(session)
    kinds = [e["kind"] for e in timeline]
    assert kinds == ["stage_changed", "call", "created"]
    assert timeline[1]["contact_name"] == "Jane Doe"
    assert timeline[0]["company"] == "Acme"


def test_history_timeline_respects_limit(session):
    for i in range(5):
        repo.create_application(session, job_id=None, company=f"C{i}", title=f"T{i}", applied_at=utcnow())
    assert len(repo.history_timeline(session, limit=2)) == 2
