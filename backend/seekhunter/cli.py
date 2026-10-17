import argparse
import json
import logging
import sys
from collections.abc import Callable

from sqlmodel import Session

from seekhunter import repo
from seekhunter.config import Env, get_env
from seekhunter.db import get_engine, init_db
from seekhunter.lock import RunLocked, run_lock
from seekhunter.notify import Notifier


def _build_contact_lookup(env: Env) -> Callable[[str, str], str | None] | None:
    if not env.brave_api_key:
        return None
    from seekhunter.contacts import find_linkedin_profile

    return lambda name, company: find_linkedin_profile(name, company, env.brave_api_key)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seekhunter")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="crawl, evaluate, notify")
    run.add_argument("--dry-run", action="store_true", help="print Telegram messages instead of sending")
    recap = sub.add_parser("recap", help="send today's recap")
    recap.add_argument("--dry-run", action="store_true")
    sub.add_parser("notify-test", help="send a test Telegram message")
    sub.add_parser("rescore", help="re-score recent jobs after a resume change (no LLM, no notifications)")
    contacts = sub.add_parser("contacts", help="backfill recruiter contacts for recently seen jobs")
    contacts.add_argument("--days", type=int, default=7)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    env = get_env()
    init_db()
    notifier = Notifier(env.openclaw_bin, env.telegram_target, dry_run=getattr(args, "dry_run", False))

    if args.command == "notify-test":
        notifier.send("SeekHunter test message")
        return 0

    try:
        blocking = args.command in ("rescore", "contacts")
        with run_lock(env.data_dir, blocking=blocking), Session(get_engine()) as session:
            repo.ensure_seed(session)
            if args.command == "rescore":
                from seekhunter.pipeline import run_rescore
                from seekhunter.profile import load_profile

                print(f"rescored {run_rescore(session, load_profile(env.resume_dir))} jobs")
                return 0

            if args.command == "recap":
                from seekhunter.pipeline import run_recap

                run_recap(session, notifier, env.public_url, dry_run=args.dry_run)
                return 0

            if args.command == "contacts":
                from seekhunter.http import PoliteClient
                from seekhunter.pipeline import run_contacts_backfill
                from seekhunter.sources.seek import SeekSource

                report = run_contacts_backfill(
                    session, SeekSource(PoliteClient()), _build_contact_lookup(env), days=args.days)
                print(json.dumps(report, default=str, indent=1))
                return 0

            from seekhunter.llm.chain import build_chain
            from seekhunter.pipeline import run_crawl
            from seekhunter.profile import load_profile
            from seekhunter.sources import build_sources

            profile = load_profile(env.resume_dir)
            llm = build_chain(repo.load_settings(session), env)
            report = run_crawl(session, build_sources(), llm, notifier, profile, env.public_url,
                               dry_run=args.dry_run, contact_lookup=_build_contact_lookup(env))
            print(json.dumps(report.__dict__, default=str, indent=1))
            return 0
    except RunLocked:
        print("another run is in progress", file=sys.stderr)
        return 75


if __name__ == "__main__":
    sys.exit(main())
