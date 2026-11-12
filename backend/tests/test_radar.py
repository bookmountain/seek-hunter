from dataclasses import replace
from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from seekhunter import radar, repo
from seekhunter.domain import JobData
from seekhunter.models import Job, RadarCompany, Run, utcnow
from seekhunter.pipeline import run_crawl
from seekhunter.sources.ats import ATSError, build_ats_clients
from seekhunter.sources.ats.detect import detect_ats, detect_from_text, slug_candidates
from tests.test_ats_clients import FakeHTTP, Resp, load
from tests.test_pipeline import PROFILE, FakeChain, FakeNotifier, FakeSource, jd

GH = "https://boards-api.greenhouse.io/v1/boards"


def no_sleep(_):
    return None


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.ensure_seed(s)
        for p in repo.list_search_profiles(s)[1:]:
            p.enabled = False
            s.add(p)
        s.commit()
        yield s


# ---------------------------------------------------------------- detection


@pytest.mark.parametrize("text,ats,token", [
    ("https://boards.greenhouse.io/cultureamp", "greenhouse", "cultureamp"),
    ("https://job-boards.greenhouse.io/cultureamp/jobs/8367638", "greenhouse", "cultureamp"),
    ('<iframe src="https://boards.greenhouse.io/embed/job_board?for=acme&b=x">', "greenhouse", "acme"),
    ('<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme2">', "greenhouse", "acme2"),
    ('<a href="https://jobs.lever.co/immutable/46e44c79">', "lever", "immutable"),
    ("https://jobs.ashbyhq.com/airwallex", "ashby", "airwallex"),
    ("https://apply.workable.com/rokt/j/78589A4D7B/", "workable", "rokt"),
    ("https://rokt.workable.com/", "workable", "rokt"),
    ("https://jobs.smartrecruiters.com/Canva/6000000001554836-x", "smartrecruiters", "Canva"),
    ("https://careers.smartrecruiters.com/Canva", "smartrecruiters", "Canva"),
    ("https://telstra.wd3.myworkdayjobs.com/en-US/Telstra_Careers", "workday", "telstra.wd3/Telstra_Careers"),
    ("https://telstra.wd3.myworkdayjobs.com/Telstra_Careers/job/x/SRE_1", "workday",
     "telstra.wd3/Telstra_Careers"),
    ('<a href="https://secure.dc2.pageuppeople.com/apply/873/gateway">', "pageup",
     "secure.dc2.pageuppeople.com/apply/873"),
])
def test_detect_from_text(text, ats, token):
    d = detect_from_text(text)
    assert (d.ats, d.token) == (ats, token)


def test_detect_from_text_none_for_plain_pages():
    assert detect_from_text("<html><a href='/careers/dev'>Developer</a></html>") is None


def test_slug_candidates():
    assert slug_candidates("Culture Amp Pty Ltd") == ["cultureamp", "culture-amp"]
    assert slug_candidates("Immutable") == ["immutable"]
    assert slug_candidates("AB") == []


def _clients(routes):
    http = FakeHTTP(routes)
    return http, build_ats_clients(http)


def test_detect_ats_reads_the_careers_page():
    page = '<html><iframe src="https://jobs.lever.co/immutable?embed"></iframe></html>'
    http, clients = _clients({("GET", "https://acme.example/careers"): Resp(None, 200, page)})
    d = detect_ats(http, clients, name="Immutable", careers_url="https://acme.example/careers")
    assert (d.ats, d.token, d.careers_url) == ("lever", "immutable", "https://acme.example/careers")


def test_detect_ats_unknown_careers_page_is_other():
    http, clients = _clients({("GET", "https://acme.example/careers"): Resp(None, 200, "<html>jobs</html>")})
    d = detect_ats(http, clients, name="Zz", careers_url="https://acme.example/careers")
    assert (d.ats, d.token, d.careers_url) == ("other", None, "https://acme.example/careers")


def test_detect_ats_guesses_board_from_name_needs_an_australian_posting():
    http, clients = _clients({
        ("GET", f"{GH}/cultureamp/"): Resp(load("greenhouse_cultureamp.json")),
    })
    d = detect_ats(http, clients, name="Culture Amp")
    assert (d.ats, d.token) == ("greenhouse", "cultureamp")

    us_only = {"jobs": [{"id": 1, "title": "Dev", "location": {"name": "New York"}, "absolute_url": "u"}]}
    http, clients = _clients({("GET", f"{GH}/acme/"): Resp(us_only)})
    assert detect_ats(http, clients, name="Acme") is None


# ---------------------------------------------------------------- seeding


def _seen(session, company, title="React Developer", source="seek", off_topic=False, days_ago=1,
          city="adelaide"):
    ext = f"{company}-{title}-{source}"
    job, _ = repo.upsert_job(session, jd(source, ext, title=title, company=company))
    job.first_seen_at = utcnow() - timedelta(days=days_ago)
    job.city = city
    session.add(job)
    session.commit()
    repo.save_evaluation(session, job.id, excluded=off_topic, reasons=["off_topic"] if off_topic else [],
                         snippets={}, rule_score=50, final_score=50, matched_skills=[], flags=[])
    return job


def test_seed_candidates_exclude_agencies_off_topic_old_and_known(session):
    settings = repo.load_settings(session)
    _seen(session, "Culture Amp")
    _seen(session, "Culture Amp Pty Ltd", title="Data Engineer")
    _seen(session, "Hays")
    _seen(session, "Talent International")
    _seen(session, "Robert Walters")
    _seen(session, "Acme Recruitment")
    _seen(session, "Plumbing Co", title="Plumber", off_topic=True)
    _seen(session, "Old Co", days_ago=90)
    _seen(session, "Known Co")
    session.add(RadarCompany(name="Known Co", company_key="knownco"))
    session.commit()
    got = radar.seed_candidates(session, settings, utcnow())
    assert [(n, c, k) for n, c, k in got] == [("Culture Amp", "adelaide", 2)]


def test_seed_companies_adds_found_boards_and_records_misses(session):
    _seen(session, "Culture Amp")
    _seen(session, "Nowhere Widgets")
    http, clients = _clients({
        ("GET", f"{GH}/cultureamp/"): Resp(load("greenhouse_cultureamp.json")),
    })
    report = radar.seed_companies(session, repo.load_settings(session), http, clients)
    assert report["found"] == 1 and report["missed"] == 1
    rows = {c.name: c for c in radar.list_companies(session)}
    assert (rows["Culture Amp"].ats, rows["Culture Amp"].ats_token) == ("greenhouse", "cultureamp")
    assert rows["Culture Amp"].enabled and rows["Culture Amp"].source == "auto"
    assert rows["Culture Amp"].city == "adelaide"
    assert rows["Nowhere Widgets"].enabled is False
    # misses aren't probed again
    assert radar.seed_candidates(session, repo.load_settings(session), utcnow()) == []


# ---------------------------------------------------------------- polling


class FakeATS:
    ats = "greenhouse"

    def __init__(self, jobs, fail=False, details=None):
        self.jobs, self.fail, self.detail_map = jobs, fail, details or {}
        self.detail_calls = 0

    def list_jobs(self, company):
        if self.fail:
            raise ATSError("greenhouse x: HTTP 404")
        return [replace(j, company=company.name) for j in self.jobs]

    def details(self, job):
        self.detail_calls += 1
        return self.detail_map.get(job.external_id, job)


def rj(ext, title="React Developer", location="Adelaide SA", desc="<p>React TypeScript Node AWS</p>"):
    return JobData(source="radar", external_id=f"greenhouse:{ext}", title=title, company="",
                   location=location,
                   work_type="contract", url=f"https://boards/{ext}", description_html=desc,
                   listed_at=utcnow())


def _company(session, name="Acme", ats="greenhouse", enabled=True):
    c = RadarCompany(name=name, company_key=name.lower(), ats=ats, ats_token=name.lower(), enabled=enabled,
                     city="adelaide")
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def test_poll_keeps_new_australian_it_jobs_and_ignores_the_rest(session):
    acme = _company(session)
    _company(session, "Broken", enabled=True)
    _company(session, "Off", enabled=False)
    good = FakeATS([
        rj("1"), rj("2", location="New York"), rj("3", title="Sales Executive", desc="<p>Sell things</p>"),
        rj("4", title="Platform Engineer", location="Sydney"),
    ])
    clients = {"greenhouse": good}
    notifier = FakeNotifier()
    orig = good.list_jobs  # "Broken" fails, "Acme" works

    def list_jobs(company):
        if company.name == "Broken":
            raise ATSError("greenhouse broken: HTTP 404")
        return orig(company)

    good.list_jobs = list_jobs
    report = radar.run_radar(session, clients, FakeChain(), notifier, PROFILE, "https://sh", sleep=no_sleep)
    assert report.companies == 2 and report.errors == 1
    jobs = {j.external_id: j for j in session.exec(select(Job).where(Job.source == "radar")).all()}
    assert set(jobs) == {"greenhouse:1", "greenhouse:4"}
    assert jobs["greenhouse:1"].company == "Acme" and jobs["greenhouse:1"].city == "adelaide"
    assert jobs["greenhouse:4"].city == "sydney"
    assert jobs["greenhouse:1"].radar_first_seen_at is not None
    assert repo.get_evaluation(session, jobs["greenhouse:1"].id) is not None
    session.refresh(acme)
    assert set(acme.ignored_ids) == {"greenhouse:2", "greenhouse:3"}
    assert acme.last_checked_at is not None and acme.last_error is None
    broken = radar.get_company_by_key(session, "broken")
    assert "404" in broken.last_error
    run = session.exec(select(Run).where(Run.kind == "radar")).one()
    assert run.new_jobs == 2 and run.source_status["radar"]["errors"] == 1

    # a second poll creates nothing new and doesn't re-check ignored postings
    report = radar.run_radar(session, clients, FakeChain(), notifier, PROFILE, "https://sh", sleep=no_sleep)
    assert report.new_jobs == 0


def test_poll_details_then_filters(session):
    _company(session)
    bare = [rj("1", desc=""), rj("2", title="Retail Assistant", desc="")]
    ats = FakeATS(bare, details={"greenhouse:1": rj("1", location="Adelaide, Australia")})
    radar.run_radar(session, {"greenhouse": ats}, FakeChain(), FakeNotifier(), PROFILE, "https://sh",
                    sleep=lambda s: None)
    assert ats.detail_calls == 1  # the retail title never had its page fetched
    job = session.exec(select(Job).where(Job.source == "radar")).one()
    assert job.description_html


def test_radar_job_seen_first_then_seek_takes_over_and_keeps_radar_time(session):
    _company(session)
    radar.run_radar(session, {"greenhouse": FakeATS([rj("1")])}, FakeChain(), FakeNotifier(), PROFILE,
                    "https://sh", sleep=lambda s: None)
    radar_job = session.exec(select(Job).where(Job.source == "radar")).one()
    first = radar_job.radar_first_seen_at
    seek = FakeSource("seek", [jd("seek", "s1", title="React Developer", company="Acme")])
    run_crawl(session, {"seek": seek}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    seek_job = session.exec(select(Job).where(Job.source == "seek")).one()
    session.refresh(radar_job)
    assert radar_job.canonical_job_id == seek_job.id
    assert seek_job.radar_first_seen_at == first


def test_board_duplicate_folds_into_the_radar_job(session):
    _company(session)
    radar.run_radar(session, {"greenhouse": FakeATS([rj("1")])}, FakeChain(), FakeNotifier(), PROFILE,
                    "https://sh", sleep=lambda s: None)
    jora = FakeSource("jora", [jd("jora", "j1", title="React Developer", company="Acme")])
    run_crawl(session, {"jora": jora}, FakeChain(), FakeNotifier(), PROFILE, "https://sh")
    radar_job = session.exec(select(Job).where(Job.source == "radar")).one()
    jora_job = session.exec(select(Job).where(Job.source == "jora")).one()
    assert jora_job.canonical_job_id == radar_job.id


def test_radar_instant_alert_for_strong_new_job(session):
    from tests.test_instant_alerts import HighChain

    _company(session)
    settings = repo.load_settings(session)
    settings.instant_alert_min_score = 50
    repo.save_settings(session, settings)
    notifier = FakeNotifier()
    report = radar.run_radar(session, {"greenhouse": FakeATS([rj("1")])}, HighChain(), notifier, PROFILE,
                             "https://sh", sleep=lambda s: None)
    assert report.alerted == 1
    assert notifier.sent[0].startswith("Just posted") and "· radar" in notifier.sent[0]


def test_radar_disabled_skips_polling_but_poll_now_works(session):
    c = _company(session)
    settings = repo.load_settings(session)
    settings.radar_enabled = False
    repo.save_settings(session, settings)
    ats = FakeATS([rj("1")])
    assert radar.run_radar(session, {"greenhouse": ats}, FakeChain(), FakeNotifier(), PROFILE, "x",
                           sleep=lambda s: None).companies == 0
    assert radar.run_radar(session, {"greenhouse": ats}, FakeChain(), FakeNotifier(), PROFILE, "x",
                           company_ids=[c.id], sleep=lambda s: None).new_jobs == 1


# ---------------------------------------------------------------- changedetection.io


def test_parse_changedetection_apprise_body():
    payload = {"version": "1.0", "title": "SeekHunter radar: Acme careers",
               "message": "watch_url: https://acme.example/careers\n(added) Senior Software Engineer\n",
               "type": "info"}
    p = radar.parse_changedetection(payload)
    assert p.url == "https://acme.example/careers"
    assert "Senior Software Engineer" in p.text


def test_parse_changedetection_flat_json():
    p = radar.parse_changedetection({"url": "https://a/careers", "diff_added": "Data Engineer"})
    assert (p.url, p.text) == ("https://a/careers", "Data Engineer")


def test_extract_roles_from_diff(session):
    settings = repo.load_settings(session)
    text = "\n".join([
        "watch_url: https://acme.example/careers",
        "(added) Senior Software Engineer - Adelaide https://acme.example/careers/123",
        "(added) Graduate Developer",
        "(removed) Junior Developer",
        "(added) Retail Store Manager",
        "(added) We are hiring across our teams and would love to hear from you today.",
        "(added) Apply now",
        "(added) Graduate Developer",
        "(added) Cloud Platform Engineer https://acme.example/careers",
    ])
    roles = radar.extract_roles(text, settings, base_url="https://acme.example/careers")
    assert roles == [
        ("Senior Software Engineer - Adelaide", "https://acme.example/careers/123"),
        ("Graduate Developer", None),
        ("Cloud Platform Engineer", None),
    ]


def test_match_company_by_url(session):
    a = RadarCompany(name="Acme", company_key="acme", careers_url="https://www.acme.example/careers/")
    b = RadarCompany(name="Beta", company_key="beta", careers_url="https://beta.example/jobs")
    session.add_all([a, b])
    session.commit()
    assert radar.match_company_by_url(session, "http://acme.example/careers").name == "Acme"
    assert radar.match_company_by_url(session, "https://beta.example/jobs/search?q=1").name == "Beta"
    assert radar.match_company_by_url(session, "https://gamma.example/") is None


def test_ingest_webhook_then_pending_run_fills_details_and_scores(session):
    c = RadarCompany(name="Acme", company_key="acme", ats="other", careers_url="https://acme.example/careers",
                     city="adelaide")
    session.add(c)
    session.commit()
    session.refresh(c)
    roles = [("Senior Software Engineer", "https://acme.example/careers/123"), ("Graduate Developer", None)]
    created = radar.ingest_webhook(session, c, roles, "https://acme.example/careers")
    assert len(created) == 2
    assert all(j.needs_details and j.source == "radar" and j.location == "Adelaide SA" for j in created)
    assert created[1].url == "https://acme.example/careers"
    # same diff again: nothing new
    assert radar.ingest_webhook(session, c, roles, "https://acme.example/careers") == []

    page = ("<html><body><nav>menu</nav><main><h1>Senior Software Engineer</h1><p>React TypeScript</p>"
            "</main></body></html>")
    http = FakeHTTP({("GET", "https://acme.example/careers/123"): Resp(None, 200, page)})
    report = radar.run_radar(session, {}, FakeChain(), FakeNotifier(), PROFILE, "x", http=http, poll=False)
    assert report.details_filled == 2
    # only the ad link is fetched, never the careers page itself
    assert [call[1] for call in http.calls] == ["https://acme.example/careers/123"]
    jobs = session.exec(select(Job).where(Job.source == "radar").order_by(Job.id)).all()
    assert "React TypeScript" in jobs[0].description_html and "menu" not in jobs[0].description_html
    assert not any(j.needs_details for j in jobs)
    assert all(repo.get_evaluation(session, j.id) is not None for j in jobs)
