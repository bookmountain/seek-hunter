import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

WORK_TYPE_LABELS = {"full_time": "Full time", "part_time": "Part time", "contract": "Contract",
                    "casual": "Casual", "unknown": "Not stated"}
PER_MESSAGE = 10
MAX_CHARS = 3800
RECAP_MAX_ITEMS = 15
NOTE_LIMIT = 80
_GENERIC_LOCATION = "Adelaide SA"
_JORA_HEX_ID = re.compile(r"([0-9a-fA-F]{32})$")


class NotifyError(Exception):
    pass


@dataclass
class DigestItem:
    job_id: int
    score: int
    title: str
    company: str
    location: str
    work_type: str
    matched: list[str]
    why: str | None
    url: str
    flags: list[str] = field(default_factory=list)
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    applicant_count: int | None = None
    already_applied_title: str | None = None
    already_applied_days_ago: int | None = None


def _strip_scheme(url: str) -> str:
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    if url.startswith("www."):
        url = url[4:]
    return url


def _short_url(url: str) -> str:
    """Drop the scheme/www so Telegram still auto-links the bare domain, and collapse Jora's
    long slug-plus-id path down to its id (Jora resolves any slug prefix before the id)."""
    short = _strip_scheme(url)
    if short.startswith("au.jora.com/job/"):
        m = _JORA_HEX_ID.search(short)
        if m:
            short = f"au.jora.com/job/j-{m.group(1)}"
    return short


def _short_location(location: str) -> str | None:
    if not location or location == _GENERIC_LOCATION:
        return None
    if "," in location:
        return location.split(",", 1)[0].strip()
    return location


def _truncate_note(note: str, limit: int = NOTE_LIMIT) -> str:
    note = note.strip()
    if len(note) <= limit:
        return note
    cut = note[: limit - 1]
    sp = cut.rfind(" ")
    if sp > 0:
        cut = cut[:sp]
    return cut.rstrip(" ,.;:") + "…"


def _note_line(it: DigestItem) -> str | None:
    if it.why:
        return _truncate_note(it.why)
    if it.matched:
        return ", ".join(it.matched[:4])
    return None


def _meta_line(it: DigestItem) -> str:
    work_type = WORK_TYPE_LABELS.get(it.work_type, "Not stated")
    parts = [it.company, work_type]
    loc = _short_location(it.location)
    if loc:
        parts.append(loc)
    line = " · ".join(parts)
    if "hours" in it.flags:
        line += " · over 24h/wk"
    if "police_check" in it.flags:
        line += " · police check"
    if it.applicant_count is not None:
        line += f" · {it.applicant_count} applicants"
    return line


def _contact_line(it: DigestItem) -> str | None:
    parts = []
    if it.contact_name:
        parts.append(it.contact_name)
    if it.contact_phone:
        parts.append(it.contact_phone)
    elif it.contact_email:
        parts.append(it.contact_email)
    return " · ".join(parts) if parts else None


def _app_base(public_url: str) -> str:
    """Full clickable app URL (Telegram doesn't reliably auto-link bare hosts like *.work)."""
    url = public_url.rstrip("/")
    return url if url.startswith(("http://", "https://")) else f"https://{url}"


def _already_applied_line(it: DigestItem) -> str | None:
    if it.already_applied_title is None or it.already_applied_days_ago is None:
        return None
    return f"Already applied: {it.already_applied_title} ({it.already_applied_days_ago}d ago)"


def _format_item(it: DigestItem, app_base: str | None = None) -> str:
    lines = [f"#{it.job_id} · {it.score} · {it.title}", _meta_line(it)]
    already_line = _already_applied_line(it)
    if already_line:
        lines.append(already_line)
    contact_line = _contact_line(it)
    if contact_line:
        lines.append(contact_line)
    note_line = _note_line(it)
    if note_line:
        lines.append(note_line)
    # Deep link into the app (job detail has the SEEK/Jora link); fall back to the ad link.
    lines.append(f"{app_base}/?job={it.job_id}" if app_base else _short_url(it.url))
    return "\n".join(lines)


def _pack_items(items: list[DigestItem], app_base: str | None = None) -> list[list[DigestItem]]:
    """Group items into chunks that fit Telegram's message-size limit.

    A chunk never exceeds PER_MESSAGE items, and starting a new item never pushes the chunk's
    formatted body past MAX_CHARS (leaving room for the header/footer added around the body).
    Items within a chunk are later joined with a blank line, so the separator overhead is 2
    chars rather than 1.
    """
    chunks: list[list[DigestItem]] = []
    current: list[DigestItem] = []
    current_len = 0
    for it in items:
        text = _format_item(it, app_base)
        added_len = len(text) + (2 if current else 0)
        if current and (len(current) >= PER_MESSAGE or current_len + added_len > MAX_CHARS):
            chunks.append(current)
            current, current_len, added_len = [], 0, len(text)
        current.append(it)
        current_len += added_len
    if current:
        chunks.append(current)
    return chunks or [[]]


def _host(public_url: str) -> str:
    return _strip_scheme(public_url).rstrip("/")


def _assemble(header: str, job_texts: list[str], footer: str | None) -> str:
    sections = [header, *job_texts]
    if footer:
        sections.append(footer)
    return "\n\n".join(sections)


def format_digest(items: list[DigestItem], when: datetime, public_url: str, degraded: list[str],
                  extra: int = 0) -> list[str]:
    total = len(items) + extra
    # `extra` jobs beyond this page aren't DigestItems here, so the flexible count can only
    # reflect the items actually shown in this digest.
    flexible = sum(1 for it in items if "flexible" in it.flags)
    header_lines = [f"SeekHunter — {total} new, {flexible} flexible ({when:%H:%M})"]
    if degraded:
        names = ", ".join(s.capitalize() for s in degraded)
        header_lines.append(f"{names} unavailable this run")
    header = "\n".join(header_lines)

    base = _app_base(public_url)
    chunks = _pack_items(items, base)
    n_chunks = len(chunks)
    host = base
    first_id = items[0].job_id if items else ""
    messages = []
    for idx, chunk in enumerate(chunks):
        job_texts = [_format_item(it, base) for it in chunk]
        head = header if idx == 0 else f"SeekHunter — continued ({idx + 1}/{n_chunks})"
        footer = None
        if idx == n_chunks - 1:
            more_line = f"+{extra} more: {host}" if extra else host
            reply_line = f"Reply to OpenClaw: save {first_id} · hide {first_id} · why {first_id}"
            footer = f"{more_line}\n{reply_line}"
        messages.append(_assemble(head, job_texts, footer))
    return messages


def _follow_up_line(follow_ups: list[dict]) -> str:
    bits = ", ".join(f"{f['company']} · {f['title']} · {f['days']}d" for f in follow_ups[:3])
    return f"Follow up: {bits}"


def format_recap(items: list[DigestItem], excluded: int, day: str, public_url: str,
                 follow_ups: list[dict] | None = None) -> list[str]:
    shown = items[:RECAP_MAX_ITEMS]
    extra = max(0, len(items) - RECAP_MAX_ITEMS)
    header = f"SeekHunter daily recap — {day}"
    summary = f"{len(items)} new jobs, {excluded} excluded"
    base = _app_base(public_url)
    chunks = _pack_items(shown, base)
    n_chunks = len(chunks)
    host = base
    first_id = shown[0].job_id if shown else ""
    messages = []
    for idx, chunk in enumerate(chunks):
        job_texts = [_format_item(it, base) for it in chunk]
        head = header if idx == 0 else f"SeekHunter daily recap — continued ({idx + 1}/{n_chunks})"
        if idx == 0:
            head = f"{head}\n{summary}"
        footer = None
        if idx == n_chunks - 1:
            more_line = f"+{extra} more: {host}" if extra else host
            reply_line = f"Reply to OpenClaw: save {first_id} · hide {first_id} · why {first_id}"
            footer = f"{more_line}\n{reply_line}"
            if follow_ups:
                footer = f"{footer}\n{_follow_up_line(follow_ups)}"
        messages.append(_assemble(head, job_texts, footer))
    return messages


def format_brief(*, job_id: int, title: str, company: str, location: str, work_type: str,
                 salary: str | None, score: int, rule_score: int, llm_score: int | None,
                 llm_note: str | None, matched: list[str], missing: list[str], flags: list[str],
                 reasons: list[str], status: str, url: str, description: str,
                 contact_name: str | None = None, contact_phone: str | None = None,
                 contact_email: str | None = None, contact_linkedin: str | None = None,
                 contact_search: dict | None = None, competition: str | None = None) -> str:
    lines = [
        f"#{job_id} {title} — {company} · {location} · {WORK_TYPE_LABELS.get(work_type, work_type)}"
        + (f" · {salary}" if salary else ""),
        f"Score {score} (rules {rule_score}" + (f", AI {llm_score}" if llm_score is not None else "") + ")"
        + f" · status {status}",
    ]
    if llm_note:
        lines.append(f"AI note: {llm_note}")
    lines.append(f"Matched: {', '.join(matched) or '-'}")
    lines.append(f"Missing: {', '.join(missing) or '-'}")
    if flags:
        lines.append(f"Flags: {', '.join(flags)}")
    if reasons:
        lines.append(f"Excluded for: {', '.join(reasons)}")
    if competition:
        lines.append(f"Competition: {competition}")
    contact_bits = [b for b in (contact_name, contact_phone, contact_email) if b]
    if contact_bits:
        lines.append(f"Recruiter: {' · '.join(contact_bits)}")
    linkedin = contact_linkedin or (contact_search or {}).get("linkedin")
    if linkedin:
        lines.append(f"LinkedIn: {linkedin}")
    lines.append(f"URL: {url}")
    lines.append("")
    lines.append(description[:3500])
    return "\n".join(lines)


def format_market_brief(overview: list[dict], top_skills: list[dict], top_gaps: list[dict],
                        head_to_head: list[str], best_flexible_city: str, best_flexible_share: float,
                        public_url: str) -> str:
    """Plain-text weekly market-insights brief: per-city totals/flexible share, Adelaide's top
    skills (with "you have" markers), the biggest gaps, head-to-head lines, and the best city
    for flexible work. No emoji, short lines, matching the rest of this module's style."""
    lines = ["SeekHunter weekly market brief"]
    for row in overview:
        pct = row["flexible_share"] * 100
        lines.append(f"{row['city'].capitalize()}: {row['total']} jobs, {pct:.0f}% flexible")
    if top_skills:
        lines.append("")
        lines.append("Top skills in Adelaide:")
        for s in top_skills[:5]:
            mark = "have" if s["you_have"] else "gap"
            lines.append(f"- {s['skill']} {s['share'] * 100:.0f}% ({mark})")
    if top_gaps:
        lines.append("")
        lines.append("Biggest gaps:")
        for g in top_gaps[:3]:
            lines.append(f"- {g['skill']} {g['share'] * 100:.0f}%")
    if head_to_head:
        lines.append("")
        lines.extend(head_to_head)
    lines.append("")
    lines.append(f"Best city for flexible roles: {best_flexible_city.capitalize()} "
                 f"({best_flexible_share * 100:.0f}%)")
    lines.append(f"{_app_base(public_url)}/insights")
    return "\n".join(lines)


DEFAULT_OPENCLAW_MEDIA_DIR = Path.home() / ".openclaw" / "media" / "outbound" / "seekhunter"


class Notifier:
    def __init__(self, bin_path: str, target: str, dry_run: bool = False,
                 media_dir: Path = DEFAULT_OPENCLAW_MEDIA_DIR) -> None:
        self.bin_path, self.target, self.dry_run = bin_path, target, dry_run
        self.media_dir = media_dir

    def send(self, text: str) -> None:
        if self.dry_run:
            print(f"--- [dry-run telegram → {self.target}] ---\n{text}\n")
            return
        cmd = [
            self.bin_path, "message", "send", "--channel", "telegram",
            "--target", self.target, "--message", text,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise NotifyError(str(e)) from e
        if proc.returncode != 0:
            raise NotifyError(f"exit {proc.returncode}: {proc.stderr[-300:]}")

    def send_file(self, path: Path, caption: str) -> None:
        """Send `path` as a Telegram document (not a compressed photo) with `caption`."""
        if self.dry_run:
            print(f"--- [dry-run telegram file → {self.target}] {path} ---\n{caption}\n")
            return
        # OpenClaw only reads local media from its own media dir, so stage a copy there first.
        staged = self.media_dir / uuid.uuid4().hex[:12] / path.name  # keep the clean file name
        try:
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, staged)
        except OSError as e:
            raise NotifyError(f"cannot stage {path} in {self.media_dir}: {e}") from e
        cmd = [
            self.bin_path, "message", "send", "--channel", "telegram", "--target", self.target,
            "--media", str(staged), "--force-document", "--message", caption,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise NotifyError(str(e)) from e
        finally:
            shutil.rmtree(staged.parent, ignore_errors=True)
        if proc.returncode != 0:
            raise NotifyError(f"exit {proc.returncode}: {proc.stderr[-300:]}")
