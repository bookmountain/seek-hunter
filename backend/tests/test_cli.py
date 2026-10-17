from seekhunter import cli


def test_parser_commands():
    p = cli.build_parser()
    assert p.parse_args(["run", "--dry-run"]).dry_run is True
    assert p.parse_args(["recap"]).command == "recap"
    assert p.parse_args(["notify-test"]).command == "notify-test"
