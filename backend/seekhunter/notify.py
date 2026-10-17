import subprocess
from dataclasses import dataclass, field
from datetime import datetime

WORK_TYPE_LABELS = {"full_time": "Full time", "part_time": "Part time", "contract": "Contract",
                    "casual": "Casual", "unknown": "Type n/a"}
PER_MESSAGE = 10
MAX_CHARS = 3800
REPLY_HINT = "💬 Reply to OpenClaw: \"save #id\", \"hide #id\", \"why #id?\""


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


def _format_item(it: DigestItem) -> str:
    badges = (" 💼" if "flexible" in it.flags else "") + (" ⚠️ hours" if "hours" in it.flags else "")
    work_type = WORK_TYPE_LABELS.get(it.work_type, "Type n/a")
    line1 = f"#{it.job_id} [{it.score}] {it.title} — {it.company} · {it.location} · {work_type}{badges}"
    details = []
    if it.matched:
        details.append(f"{', '.join(it.matched[:5])} ✓")
    if it.why:
        details.append(f'"{it.why}"')
    lines = [line1]
    if details:
        lines.append("   " + " · ".join(details))
    lines.append(f"   {it.url}")
    return "\n".join(lines)


def _pack_items(items: list[DigestItem]) -> list[list[DigestItem]]:
    """Group items into chunks that fit Telegram's message-size limit.

    A chunk never exceeds PER_MESSAGE items, and starting a new item never pushes the chunk's
    formatted body past MAX_CHARS (leaving room for the header/footer added around the body).
    """
    chunks: list[list[DigestItem]] = []
    current: list[DigestItem] = []
    current_len = 0
    for it in items:
        text = _format_item(it)
        added_len = len(text) + (1 if current else 0)
        if current and (len(current) >= PER_MESSAGE or current_len + added_len > MAX_CHARS):
            chunks.append(current)
            current, current_len, added_len = [], 0, len(text)
        current.append(it)
        current_len += added_len
    if current:
        chunks.append(current)
    return chunks or [[]]


def format_digest(items: list[DigestItem], when: datetime, public_url: str, degraded: list[str],
                  extra: int = 0) -> list[str]:
    header = f"🎯 SeekHunter · {len(items) + extra} new ({when:%H:%M})"
    if degraded:
        header += "\n" + " ".join(f"⚠️ {s} unavailable this run" for s in degraded)
    chunks = _pack_items(items)
    messages = []
    for idx, chunk in enumerate(chunks):
        body = "\n".join(_format_item(it) for it in chunk)
        parts = [header if idx == 0 else f"🎯 SeekHunter · cont. ({idx + 1}/{len(chunks)})", body]
        if idx == len(chunks) - 1:
            if extra:
                parts.append(f"+{extra} more in the web UI")
            parts.append(REPLY_HINT)
            parts.append(f"→ {public_url}")
        messages.append("\n".join(p for p in parts if p))
    return messages


def format_recap(items: list[DigestItem], excluded: int, day: str, public_url: str) -> list[str]:
    header = f"🎯 SeekHunter daily recap · {day}"
    summary = f"{len(items)} new jobs · {excluded} excluded"
    chunks = _pack_items(items)
    messages = []
    for idx, chunk in enumerate(chunks):
        body = "\n".join(_format_item(it) for it in chunk)
        parts = [header if idx == 0 else f"🎯 SeekHunter daily recap · cont. ({idx + 1}/{len(chunks)})"]
        if idx == 0:
            parts.append(summary)
        parts.append(body)
        if idx == len(chunks) - 1:
            parts.append(f"→ {public_url}")
        messages.append("\n".join(p for p in parts if p))
    return messages


def format_brief(*, job_id: int, title: str, company: str, location: str, work_type: str,
                 salary: str | None, score: int, rule_score: int, llm_score: int | None,
                 llm_note: str | None, matched: list[str], missing: list[str], flags: list[str],
                 reasons: list[str], status: str, url: str, description: str) -> str:
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
    lines.append(f"URL: {url}")
    lines.append("")
    lines.append(description[:3500])
    return "\n".join(lines)


class Notifier:
    def __init__(self, bin_path: str, target: str, dry_run: bool = False) -> None:
        self.bin_path, self.target, self.dry_run = bin_path, target, dry_run

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
