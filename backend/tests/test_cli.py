from seekhunter import cli
from seekhunter.config import Env


def test_parser_commands():
    p = cli.build_parser()
    assert p.parse_args(["run", "--dry-run"]).dry_run is True
    assert p.parse_args(["recap"]).command == "recap"
    assert p.parse_args(["notify-test"]).command == "notify-test"


def test_parser_rescore():
    assert cli.build_parser().parse_args(["rescore"]).command == "rescore"


def test_parser_contacts_defaults_to_seven_days():
    args = cli.build_parser().parse_args(["contacts"])
    assert args.command == "contacts"
    assert args.days == 7


def test_parser_contacts_days_override():
    args = cli.build_parser().parse_args(["contacts", "--days", "3"])
    assert args.days == 3


def test_parser_insights_defaults_to_sixty():
    args = cli.build_parser().parse_args(["insights"])
    assert args.command == "insights"
    assert args.limit == 60


def test_parser_insights_limit_override():
    args = cli.build_parser().parse_args(["insights", "--limit", "10"])
    assert args.limit == 10


def test_build_contact_lookup_none_without_brave_key():
    assert cli._build_contact_lookup(Env(brave_api_key=None)) is None


def test_build_contact_lookup_present_with_brave_key(monkeypatch):
    calls = {}

    def fake_find(name, company, api_key):
        calls["args"] = (name, company, api_key)
        return "https://www.linkedin.com/in/x"

    monkeypatch.setattr("seekhunter.contacts.find_linkedin_profile", fake_find)
    lookup = cli._build_contact_lookup(Env(brave_api_key="k3y"))
    assert lookup is not None
    assert lookup("Jane Doe", "Acme") == "https://www.linkedin.com/in/x"
    assert calls["args"] == ("Jane Doe", "Acme", "k3y")


def test_parser_tailor():
    args = cli.build_parser().parse_args(["tailor", "7"])
    assert (args.command, args.job_id, args.tailoring_id, args.send) == ("tailor", 7, None, False)
    args = cli.build_parser().parse_args(["tailor", "7", "--tailoring-id", "3", "--send"])
    assert (args.tailoring_id, args.send) == (3, True)


def test_parser_resume_preview():
    assert cli.build_parser().parse_args(["resume-preview"]).command == "resume-preview"


def test_tailor_command_creates_row_and_runs_pipeline(monkeypatch, tmp_path):
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine

    from seekhunter import repo
    from seekhunter.domain import JobData
    from seekhunter.models import Tailoring

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        job, _ = repo.upsert_job(s, JobData(source="seek", external_id="1", title="Dev", company="A",
                                            location="", work_type="contract", url="u"))
        job_id = job.id
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "init_db", lambda: None)
    seen = {}

    def fake_run(session, tid, **kw):
        seen["tid"], seen["kw"] = tid, kw
        t = session.get(Tailoring, tid)
        t.status = "done"
        repo.save_tailoring(session, t)
        return t

    monkeypatch.setattr("seekhunter.tailor.pipeline.run_tailoring", fake_run)
    assert cli.main(["tailor", str(job_id), "--send"]) == 0
    with Session(engine) as s:
        t = s.get(Tailoring, seen["tid"])
        assert t.job_id == job_id and t.send_requested is True
    assert callable(seen["kw"]["llm"]) and callable(seen["kw"]["compiler"])
    assert cli.main(["tailor", "999"]) == 2


def test_parser_market_defaults():
    args = cli.build_parser().parse_args(["market"])
    assert args.command == "market"
    assert args.cities is None
    assert args.dry_run is False


def test_parser_market_cities_and_dry_run():
    args = cli.build_parser().parse_args(["market", "--cities", "adelaide", "perth", "--dry-run"])
    assert args.cities == ["adelaide", "perth"]
    assert args.dry_run is True


def test_parser_insights_brief():
    assert cli.build_parser().parse_args(["insights-brief"]).dry_run is False
    assert cli.build_parser().parse_args(["insights-brief", "--dry-run"]).dry_run is True


def test_main_market_runs_crawl_with_its_own_lock(monkeypatch, tmp_path, capsys):
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "init_db", lambda: None)

    calls = {}

    class FakeSeek:
        def __init__(self, client):
            pass

        def search(self, profile, max_pages, daterange=7):
            calls["search"] = (profile.location, max_pages, daterange)
            return []

    monkeypatch.setattr("seekhunter.sources.seek.SeekSource", FakeSeek)
    assert cli.main(["market", "--cities", "adelaide"]) == 0
    assert calls["search"] == ("All Adelaide SA", 2, 14)
    assert (tmp_path / "market.lock").exists()


def test_main_market_locked_returns_75(monkeypatch, tmp_path):
    import fcntl

    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "init_db", lambda: None)
    tmp_path.mkdir(parents=True, exist_ok=True)
    fh = open(tmp_path / "market.lock", "w")  # noqa: SIM115
    fcntl.flock(fh, fcntl.LOCK_EX)
    try:
        assert cli.main(["market"]) == 75
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def test_main_insights_brief_runs_pipeline(monkeypatch, tmp_path):
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "init_db", lambda: None)
    seen = {}

    def fake_brief(session, notifier, public_url, resume_dir, dry_run=False):
        seen["args"] = (public_url, resume_dir, dry_run)

    monkeypatch.setattr("seekhunter.pipeline.run_insights_brief", fake_brief)
    assert cli.main(["insights-brief", "--dry-run"]) == 0
    assert seen["args"][2] is True
