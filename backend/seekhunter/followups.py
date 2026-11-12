"""Follow-up loop: what's due, a ready-to-send message for each, snooze/dismiss/done, and the digest.

Due rules (`days` = settings.follow_up_days, default 5):
- application_nudge: an application still in `applied` with no activity for `days` days. Activity =
  its events (stage changes), interactions logged on it, and non-note interactions with its contacts.
- linkedin_invite_pending: the contact's latest LinkedIn step is an invite sent `days`+ days ago and
  nothing else has happened with them since.
- linkedin_thank: the invite was accepted but no message has been sent yet (due straight away).
- linkedin_no_reply: a LinkedIn message sent `days`+ days ago without a reply.

Each occurrence has a stable key that embeds the triggering activity's timestamp, so snoozing,
dismissing or marking done hides only that occurrence; new activity starts a new cycle.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from sqlmodel import Session, col, select

from seekhunter import repo
from seekhunter.domain import is_agency
from seekhunter.models import (
    Application,
    ApplicationEvent,
    Contact,
    ContactJob,
    FollowUpState,
    Interaction,
    Job,
    utcnow,
)
from seekhunter.tailor.engine import first_name

FOLLOW_UP_KINDS = ("application_nudge", "linkedin_invite_pending", "linkedin_thank", "linkedin_no_reply")
LINKEDIN_KINDS = ("linkedin_invite", "linkedin_accepted", "linkedin_message", "linkedin_reply")
LINKEDIN_STATUS = {"linkedin_invite": "sent", "linkedin_accepted": "accepted",
                   "linkedin_message": "messaged", "linkedin_reply": "replied"}
REPLY_KINDS = ("linkedin_reply", "meeting")
STALE_DAYS = 30
DIGEST_MAX_ITEMS = 12
SIGN_OFF = "Thanks,\nBook Sam"
INVITE_HINT_OTHER = "Invite not accepted yet. Reach them another way, or withdraw and resend with a note."
INVITE_HINT_RESEND = "Invite not accepted yet. Withdraw it and resend with this note."


@dataclass
class FollowUp:
    key: str
    kind: str
    days: int  # since the triggering activity
    since: datetime
    company: str
    title: str
    channel: str  # email | linkedin | phone
    message: str
    subject: str | None = None
    hint: str | None = None
    application_id: int | None = None
    job_id: int | None = None
    contact_id: int | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    contact_linkedin: str | None = None
    link: str = "/history?tab=followups"

    def as_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------------------------ data index


@dataclass
class Index:
    """Everything the follow-up and funnel logic needs, loaded in a handful of queries."""

    applications: list[Application]
    jobs: dict[int, Job]
    contacts: dict[int, Contact]
    events: dict[int, list[ApplicationEvent]] = field(default_factory=dict)  # by application id
    app_interactions: dict[int, list[Interaction]] = field(default_factory=dict)  # by application id
    contact_interactions: dict[int, list[Interaction]] = field(default_factory=dict)  # by contact id
    job_contacts: dict[int, list[int]] = field(default_factory=dict)  # job id -> contact ids
    contact_jobs: dict[int, list[int]] = field(default_factory=dict)  # contact id -> job ids
    key_contacts: dict[str, list[int]] = field(default_factory=dict)  # company_key -> contact ids

    def contacts_for(self, app: Application) -> list[Contact]:
        """The application's recruiter(s): linked to its job, else (manual applications) contacts at the
        same company."""
        ids = list(self.job_contacts.get(app.job_id, [])) if app.job_id else []
        for i in self.app_interactions.get(app.id, []):
            if i.contact_id and i.contact_id not in ids:
                ids.append(i.contact_id)
        if not ids and not app.job_id:
            ids = list(self.key_contacts.get(app.company_key, []))
        return [self.contacts[c] for c in ids if c in self.contacts]

    def interactions_for(self, app: Application) -> list[Interaction]:
        """Interactions logged on the application plus those with its contacts (deduplicated)."""
        seen: dict[int, Interaction] = {i.id: i for i in self.app_interactions.get(app.id, [])}
        for c in self.contacts_for(app):
            for i in self.contact_interactions.get(c.id, []):
                seen.setdefault(i.id, i)
        return sorted(seen.values(), key=lambda i: i.at)


def load_index(session: Session) -> Index:
    apps = list(session.exec(select(Application)).all())
    job_ids = {a.job_id for a in apps if a.job_id}
    links = list(session.exec(select(ContactJob)).all())
    job_ids |= {link.job_id for link in links}
    jobs = {}
    if job_ids:
        jobs = {j.id: j for j in session.exec(select(Job).where(col(Job.id).in_(job_ids))).all()}
    contacts = {c.id: c for c in session.exec(select(Contact)).all()}
    idx = Index(applications=apps, jobs=jobs, contacts=contacts)
    for ev in session.exec(select(ApplicationEvent).order_by(col(ApplicationEvent.at))).all():
        idx.events.setdefault(ev.application_id, []).append(ev)
    for i in session.exec(select(Interaction).order_by(col(Interaction.at), col(Interaction.id))).all():
        if i.application_id:
            idx.app_interactions.setdefault(i.application_id, []).append(i)
        if i.contact_id:
            idx.contact_interactions.setdefault(i.contact_id, []).append(i)
    for link in links:
        idx.job_contacts.setdefault(link.job_id, []).append(link.contact_id)
        idx.contact_jobs.setdefault(link.contact_id, []).append(link.job_id)
    for c in contacts.values():
        idx.key_contacts.setdefault(c.company_key, []).append(c.id)
    return idx


def linkedin_status(interactions: list[Interaction]) -> str | None:
    """sent -> accepted -> messaged -> replied, from the latest LinkedIn interaction."""
    steps = [i for i in interactions if i.kind in LINKEDIN_KINDS]
    if not steps:
        return None
    latest = max(steps, key=lambda i: (i.at, i.id or 0))
    return LINKEDIN_STATUS[latest.kind]


def linkedin_statuses(session: Session, contact_ids: list[int]) -> dict[int, str]:
    if not contact_ids:
        return {}
    rows = session.exec(select(Interaction).where(col(Interaction.contact_id).in_(contact_ids),
                                                  col(Interaction.kind).in_(LINKEDIN_KINDS))).all()
    by: dict[int, list[Interaction]] = {}
    for i in rows:
        by.setdefault(i.contact_id, []).append(i)
    return {cid: s for cid, items in by.items() if (s := linkedin_status(items))}


# -------------------------------------------------------------------------------------- messages


def _greeting(contact: Contact | None) -> str:
    name = first_name(contact.name if contact else None)
    return f"Hi {name}," if name else "Hi there,"


def _role_phrase(title: str, company: str, agency: bool) -> str:
    if not title:
        return f"roles at {company}" if company else "the role"
    if agency or not company:
        return f"the {title} role"
    return f"the {title} role at {company}"


def _channel(contact: Contact | None, linkedin_connected: bool) -> str:
    if contact and contact.email:
        return "email"
    if contact and contact.linkedin and linkedin_connected:
        return "linkedin"
    if contact and contact.phone:
        return "phone"
    return "email"


def nudge_message(*, contact: Contact | None, title: str, company: str, applied_at: datetime,
                  agency: bool) -> tuple[str, str]:
    """(subject, body) for a polite application follow-up. States only facts SeekHunter knows."""
    when = f"{applied_at.day} {applied_at:%B}"
    role = _role_phrase(title, company, agency)
    body = (f"{_greeting(contact)}\n\nI applied for {role} on {when} and wanted to follow up. I'm still "
            "keen on it and happy to send anything else that would help, or to have a quick chat this "
            f"week.\n\n{SIGN_OFF}")
    return f"Following up: {title or 'my application'}", body


def invite_pending_message(contact: Contact, title: str, company: str, agency: bool) -> str:
    about = f" about {_role_phrase(title, company, agency)}" if title else ""
    return (f"{_greeting(contact)}\n\nI sent you a LinkedIn request recently{about}. I'd still like to "
            "connect and hear about any part-time or contract software roles you're working on.\n\n"
            f"{SIGN_OFF}")


def thank_message(contact: Contact, title: str, company: str, agency: bool) -> str:
    about = (f"I'm interested in {_role_phrase(title, company, agency)} and would appreciate a quick chat "
             "about it, or about any part-time or contract software roles you're working on."
             if title else "I'd appreciate a quick chat about any part-time or contract software roles "
             "you're working on.")
    return f"{_greeting(contact)}\n\nThanks for connecting. {about}\n\n{SIGN_OFF}"


def no_reply_message(contact: Contact, title: str, company: str, agency: bool) -> str:
    about = f" about {_role_phrase(title, company, agency)}" if title else ""
    return (f"{_greeting(contact)}\n\nJust following up on my message from last week{about}. Happy to "
            f"work around your schedule for a quick chat.\n\n{SIGN_OFF}")


# ----------------------------------------------------------------------------------------- rules


def _stamp(dt: datetime) -> str:
    return f"{dt:%Y%m%d%H%M%S}"


def _contact_fields(c: Contact | None) -> dict:
    if not c:
        return {}
    return {"contact_id": c.id, "contact_name": c.name, "contact_phone": c.phone, "contact_email": c.email,
            "contact_linkedin": c.linkedin}


def _app_last_activity(idx: Index, app: Application) -> datetime:
    times = [app.applied_at]
    times += [e.at for e in idx.events.get(app.id, [])]
    times += [i.at for i in idx.interactions_for(app) if i.kind != "note"]
    return max(times)


def _primary_contact(contacts: list[Contact]) -> Contact | None:
    """Prefer someone reachable by email, then LinkedIn, then phone."""
    for attr in ("email", "linkedin", "phone"):
        for c in contacts:
            if getattr(c, attr):
                return c
    return contacts[0] if contacts else None


def _app_nudges(idx: Index, now: datetime, days: int, agency_keywords: list[str]) -> list[FollowUp]:
    out = []
    cutoff = now - timedelta(days=days)
    for app in idx.applications:
        if app.stage != "applied":
            continue
        last = _app_last_activity(idx, app)
        if last > cutoff:
            continue
        contact = _primary_contact(idx.contacts_for(app))
        connected = bool(contact and linkedin_status(idx.contact_interactions.get(contact.id, []))
                         in ("accepted", "messaged", "replied"))
        agency = is_agency(app.company, agency_keywords)
        subject, body = nudge_message(contact=contact, title=app.title, company=app.company,
                                      applied_at=app.applied_at, agency=agency)
        age = (now - app.applied_at).days
        out.append(FollowUp(
            key=f"application_nudge-{app.id}-{_stamp(last)}", kind="application_nudge",
            days=(now - last).days, since=last, company=app.company, title=app.title,
            channel=_channel(contact, connected), subject=subject, message=body,
            hint=(f"No reply in {age} days: consider marking it No response." if age >= STALE_DAYS else None),
            application_id=app.id, job_id=app.job_id, **_contact_fields(contact),
            link=f"/?job={app.job_id}" if app.job_id else "/history?tab=followups"))
    return out


def _contact_job(idx: Index, contact_id: int) -> Job | None:
    jobs = [idx.jobs[j] for j in idx.contact_jobs.get(contact_id, []) if j in idx.jobs]
    return max(jobs, key=lambda j: j.first_seen_at) if jobs else None


def _linkedin_items(idx: Index, now: datetime, days: int, agency_keywords: list[str]) -> list[FollowUp]:
    out = []
    cutoff = now - timedelta(days=days)
    for cid, interactions in idx.contact_interactions.items():
        contact = idx.contacts.get(cid)
        steps = [i for i in interactions if i.kind in LINKEDIN_KINDS]
        if not contact or not steps:
            continue
        latest = max(steps, key=lambda i: (i.at, i.id or 0))
        last_any = max(i.at for i in interactions if i.kind != "note")
        job = _contact_job(idx, cid)
        title = job.title if job else ""
        company = contact.company or (job.company if job else "")
        agency = is_agency(company, agency_keywords)
        base = dict(company=company, title=title, job_id=job.id if job else None, **_contact_fields(contact),
                    link=f"/history?tab=contacts&contact={cid}")
        if latest.kind == "linkedin_invite" and latest.at <= cutoff and last_any <= cutoff:
            channel = "email" if contact.email else "phone" if contact.phone else "linkedin"
            out.append(FollowUp(
                key=f"linkedin_invite_pending-{cid}-{_stamp(latest.at)}", kind="linkedin_invite_pending",
                days=(now - latest.at).days, since=latest.at, channel=channel,
                subject=f"Connecting about {title}" if title and channel == "email" else None,
                message=invite_pending_message(contact, title, company, agency),
                hint=INVITE_HINT_OTHER if channel != "linkedin" else INVITE_HINT_RESEND,
                **base))
        elif latest.kind == "linkedin_accepted":
            out.append(FollowUp(
                key=f"linkedin_thank-{cid}-{_stamp(latest.at)}", kind="linkedin_thank",
                days=(now - latest.at).days, since=latest.at, channel="linkedin",
                message=thank_message(contact, title, company, agency), **base))
        elif latest.kind == "linkedin_message" and latest.at <= cutoff and last_any <= cutoff:
            out.append(FollowUp(
                key=f"linkedin_no_reply-{cid}-{_stamp(latest.at)}", kind="linkedin_no_reply",
                days=(now - latest.at).days, since=latest.at, channel="linkedin",
                message=no_reply_message(contact, title, company, agency), **base))
    return out


def _hidden_keys(session: Session, now: datetime) -> set[str]:
    hidden = set()
    for s in session.exec(select(FollowUpState)).all():
        if s.status in ("dismissed", "done") or (s.status == "snoozed" and s.until and s.until > now):
            hidden.add(s.key)
    return hidden


def due(session: Session, now: datetime | None = None, *, include_hidden: bool = False) -> list[FollowUp]:
    """Everything due now, longest-waiting first (LinkedIn thank-yous first: they're time-sensitive)."""
    now = now or utcnow()
    settings = repo.load_settings(session)
    idx = load_index(session)
    items = _app_nudges(idx, now, settings.follow_up_days, settings.agency_keywords)
    items += _linkedin_items(idx, now, settings.follow_up_days, settings.agency_keywords)
    if not include_hidden:
        hidden = _hidden_keys(session, now)
        items = [i for i in items if i.key not in hidden]
    items.sort(key=lambda i: (i.kind != "linkedin_thank", -i.days, i.company.casefold()))
    return items


# --------------------------------------------------------------------------------------- actions


DONE_KIND = {"email": "email", "phone": "call", "linkedin": "linkedin_message"}


def _set_state(session: Session, key: str, status: str, until: datetime | None = None) -> FollowUpState:
    row = session.exec(select(FollowUpState).where(FollowUpState.key == key)).first()
    row = row or FollowUpState(key=key, status=status)
    row.status, row.until, row.created_at = status, until, utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def snooze(session: Session, item: FollowUp, days: int, now: datetime | None = None) -> FollowUpState:
    return _set_state(session, item.key, "snoozed", (now or utcnow()) + timedelta(days=days))


def dismiss(session: Session, item: FollowUp) -> FollowUpState:
    return _set_state(session, item.key, "dismissed")


def mark_done(session: Session, item: FollowUp, note: str = "") -> Interaction | None:
    """Records that the follow-up was sent: logs the matching interaction (which also starts the next
    cycle) and hides this occurrence."""
    kind = DONE_KIND.get(item.channel)
    if item.kind == "linkedin_invite_pending" and item.channel == "linkedin":
        kind = "linkedin_invite"  # withdrawn and resent
    interaction = None
    if kind and (item.contact_id or item.application_id):
        interaction = repo.create_interaction(session, contact_id=item.contact_id,
                                              application_id=item.application_id, kind=kind,
                                              note=note or "Follow-up sent")
    _set_state(session, item.key, "done")
    return interaction


def find(session: Session, key: str, now: datetime | None = None) -> FollowUp | None:
    return next((i for i in due(session, now, include_hidden=True) if i.key == key), None)


# ---------------------------------------------------------------------------------------- digest


KIND_LABEL = {"application_nudge": "Nudge", "linkedin_invite_pending": "Invite pending",
              "linkedin_thank": "Say thanks", "linkedin_no_reply": "No reply"}


def _item_line(n: int, it: FollowUp) -> str:
    what = " · ".join(x for x in (it.company, it.title) if x)
    if it.kind == "application_nudge":
        when = f"applied, quiet {it.days}d"
    elif it.kind == "linkedin_thank":
        when = "accepted your invite"
    elif it.kind == "linkedin_invite_pending":
        when = f"invite sent {it.days}d ago"
    else:
        when = f"messaged {it.days}d ago"
    return f"{n}. {KIND_LABEL[it.kind]} · {what} · {when}"


def format_digest(items: list[FollowUp], day: str, app_base: str) -> str | None:
    """Plain-text Telegram digest, or None when nothing is due (the caller then sends nothing)."""
    if not items:
        return None
    lines = [f"SeekHunter follow-ups · {day}", f"{len(items)} due", ""]
    for n, it in enumerate(items[:DIGEST_MAX_ITEMS], 1):
        lines.append(_item_line(n, it))
        who = " · ".join(x for x in (it.contact_name, it.contact_phone or it.contact_email) if x)
        if who:
            lines.append(f"   {who} ({it.channel})")
        lines.append(f"   {app_base}{it.link}")
    if len(items) > DIGEST_MAX_ITEMS:
        lines.append(f"+{len(items) - DIGEST_MAX_ITEMS} more")
    lines += ["", f"Messages ready to copy: {app_base}/history?tab=followups"]
    return "\n".join(lines)


def format_text(items: list[FollowUp], now: datetime) -> str:
    """Plain text for agents (GET /api/follow-ups/summary): every item with its ready message."""
    if not items:
        return "No follow-ups due."
    out = [f"Follow-ups due: {len(items)}"]
    for n, it in enumerate(items, 1):
        out += ["", _item_line(n, it), f"key: {it.key}"]
        if it.contact_name:
            reach = " · ".join(x for x in (it.contact_phone, it.contact_email, it.contact_linkedin) if x)
            out.append(f"contact: {it.contact_name}" + (f" · {reach}" if reach else ""))
        if it.job_id:
            out.append(f"job: #{it.job_id}")
        out.append(f"send via: {it.channel}")
        if it.subject:
            out.append(f"subject: {it.subject}")
        out.append("message:")
        out.append(it.message)
        if it.hint:
            out.append(f"note: {it.hint}")
    return "\n".join(out)
