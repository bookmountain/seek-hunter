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
