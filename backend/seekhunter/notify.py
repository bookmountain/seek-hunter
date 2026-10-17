import subprocess
from dataclasses import dataclass, field
from datetime import datetime

WORK_TYPE_LABELS = {"full_time": "Full time", "part_time": "Part time", "contract": "Contract",
                    "casual": "Casual", "unknown": "Type n/a"}
PER_MESSAGE = 10
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
    work_type = WORK_TYPE_LABELS[it.work_type]
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


def format_digest(items: list[DigestItem], when: datetime, public_url: str, degraded: list[str],
                  extra: int = 0) -> list[str]:
    header = f"🎯 SeekHunter · {len(items)} new ({when:%H:%M})"
    if degraded:
        header += "\n" + " ".join(f"⚠️ {s} unavailable this run" for s in degraded)
    chunks = [items[i : i + PER_MESSAGE] for i in range(0, len(items), PER_MESSAGE)] or [[]]
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


def format_recap(items: list[DigestItem], excluded: int, day: str, public_url: str) -> str:
    lines = [f"🎯 SeekHunter daily recap · {day}", f"{len(items)} new jobs · {excluded} excluded"]
    lines += [_format_item(it) for it in items[:15]]
    if len(items) > 15:
        lines.append(f"+{len(items) - 15} more in the web UI")
    lines.append(f"→ {public_url}")
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
