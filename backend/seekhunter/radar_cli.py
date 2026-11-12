"""`seekhunter radar` (see cli.py): poll the Company Radar, auto-seed it, or process webhook jobs."""

import argparse
import json
import sys

from sqlmodel import Session

from seekhunter import repo
from seekhunter.config import Env
from seekhunter.db import get_engine
from seekhunter.lock import RunLocked, run_lock


def add_parser(sub) -> None:  # noqa: ANN001
    p = sub.add_parser("radar", help="poll employers' own ATS job feeds (Company Radar)")
    p.add_argument("--company", type=int, action="append", default=None,
                   help="poll just this radar company id (repeatable); works even if it's disabled")
    p.add_argument("--seed", action="store_true", help="auto-seed radar companies from recent jobs")
    p.add_argument("--pending", action="store_true",
                   help="only fill/score webhook jobs and send alerts (no feed polling)")
    p.add_argument("--dry-run", action="store_true", help="print Telegram messages instead of sending")


def main(args: argparse.Namespace, env: Env, notifier) -> int:  # noqa: ANN001
    from seekhunter import radar
    from seekhunter.sources.ats import build_ats_clients, radar_http_client

    # Scheduled polls skip when one is already running; on-demand ones (API) wait their turn.
    blocking = bool(args.seed or args.pending or args.company)
    try:
        with run_lock(env.data_dir, blocking=blocking, name="radar.lock"), Session(get_engine()) as session:
            repo.ensure_seed(session)
            http = radar_http_client()
            clients = build_ats_clients(http)
            if args.seed:
                report = radar.seed_companies(session, repo.load_settings(session), http, clients)
                print(json.dumps(report, indent=1))
                return 0
            from seekhunter.llm.chain import build_chain
            from seekhunter.profile import load_profile

            report = radar.run_radar(
                session, clients, build_chain(repo.load_settings(session), env), notifier,
                load_profile(env.resume_dir), env.public_url, http=http, company_ids=args.company,
                poll=not args.pending, dry_run=args.dry_run,
            )
            print(json.dumps(report.__dict__, default=str, indent=1))
            return 0
    except RunLocked:
        print("another radar run is in progress", file=sys.stderr)
        return 75
