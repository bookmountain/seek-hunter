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
from seekhunter.models import Job, Tailoring
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
    sub.add_parser("prune-contacts", help="remove auto-added contacts with no interaction or application")
    contacts = sub.add_parser("contacts", help="backfill recruiter contacts for recently seen jobs")
    contacts.add_argument("--days", type=int, default=7)
    insights = sub.add_parser("insights", help="refresh SEEK applicant insights on demand")
    insights.add_argument("--limit", type=int, default=60)
    market = sub.add_parser("market", help="crawl SEEK for market insights data across cities")
    market.add_argument("--cities", nargs="*", default=None,
                        help="override settings.market_cities (e.g. adelaide perth)")
    market.add_argument("--dry-run", action="store_true", help="search only, no database writes")
    brief = sub.add_parser("insights-brief", help="send the weekly market insights brief")
    brief.add_argument("--dry-run", action="store_true")
    tailor = sub.add_parser("tailor", help="tailor the resume + cover letter for one job")
    tailor.add_argument("job_id", type=int)
    tailor.add_argument("--tailoring-id", type=int, default=None,
                        help="run an existing queued tailoring row (the API creates one)")
    tailor.add_argument("--send", action="store_true", help="send both PDFs to Telegram when done")
    sub.add_parser("resume-preview", help="build/cache the PDF + PNG preview of the current resume")
    return parser


def _tailor_commands(args: argparse.Namespace, env: Env, notifier: Notifier) -> int:
    """`tailor` and `resume-preview` run under `tailor.lock`, independent of the crawl's run.lock."""
    from seekhunter.tailor import pipeline
    from seekhunter.tailor.render import tectonic_compiler

    compiler = tectonic_compiler(env.tectonic_bin)
    if args.command == "resume-preview":
        from seekhunter.tailor.current import ensure_current

        try:
            with run_lock(env.data_dir, name="tailor.lock"):
                print(json.dumps(ensure_current(env.latex_dir, env.data_dir, compiler)))
                return 0
        except RunLocked:
            print("a tailoring is in progress (it builds the preview too)", file=sys.stderr)
            return 75

    with Session(get_engine()) as session:
        job = session.get(Job, args.job_id)
        if job is None:
            print(f"job {args.job_id} not found", file=sys.stderr)
            return 2
        if args.tailoring_id is not None:
            t = session.get(Tailoring, args.tailoring_id)
            if t is None or t.job_id != job.id:
                print(f"tailoring {args.tailoring_id} not found for job {job.id}", file=sys.stderr)
                return 2
            if args.send and not t.send_requested:
                t.send_requested = True
                repo.save_tailoring(session, t)
        else:
            t = repo.create_tailoring(session, job.id, send=args.send)
        tailoring_id = t.id

    from seekhunter.tailor.engine import openclaw_llm

    with run_lock(env.data_dir, blocking=True, name="tailor.lock"), Session(get_engine()) as session:
        t = pipeline.run_tailoring(session, tailoring_id, env=env, llm=openclaw_llm(env), compiler=compiler,
                                   notifier=notifier)
        print(json.dumps({"tailoring_id": t.id, "status": t.status, "error": t.error,
                          "warnings": t.warnings}, indent=1))
        return 0 if t.status == "done" else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    env = get_env()
    init_db()
    notifier = Notifier(env.openclaw_bin, env.telegram_target, dry_run=getattr(args, "dry_run", False))

    if args.command == "notify-test":
        notifier.send("SeekHunter test message")
        return 0

    if args.command in ("tailor", "resume-preview"):
        return _tailor_commands(args, env, notifier)

    try:
        if args.command == "market":
            from seekhunter.http import PoliteClient
            from seekhunter.market import run_market_crawl
            from seekhunter.sources.seek import SeekSource

            with run_lock(env.data_dir, name="market.lock"), Session(get_engine()) as session:
                repo.ensure_seed(session)
                settings = repo.load_settings(session)
                report = run_market_crawl(session, SeekSource(PoliteClient()), settings,
                                          cities=args.cities, dry_run=args.dry_run)
                print(json.dumps(report, indent=1))
                return 0

        blocking = args.command in ("rescore", "contacts", "insights")
        with run_lock(env.data_dir, blocking=blocking), Session(get_engine()) as session:
            repo.ensure_seed(session)
            if args.command == "insights-brief":
                from seekhunter.pipeline import run_insights_brief

                run_insights_brief(session, notifier, env.public_url, env.resume_dir, dry_run=args.dry_run)
                return 0

            if args.command == "prune-contacts":
                print(f"removed {repo.prune_uncontacted_contacts(session)} uncontacted contacts")
                return 0
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

            if args.command == "insights":
                from seekhunter.http import PoliteClient
                from seekhunter.pipeline import run_insights_refresh
                from seekhunter.sources.seek import SeekSource

                notify_cities = repo.load_settings(session).notify_cities
                report = run_insights_refresh(session, SeekSource(PoliteClient()), limit=args.limit,
                                              notify_cities=notify_cities)
                print(json.dumps(report, indent=1))
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
