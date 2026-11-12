#!/usr/bin/env python3
"""Create changedetection.io watches for SeekHunter radar companies that have no pollable ATS.

For every radar company with ats "other" or "pageup", enabled, and a careers URL, make sure a
changedetection.io watch exists for that URL whose notification goes back to SeekHunter's webhook.
Existing watches (same URL) are left alone unless --update is given. Stdlib only.

Run it somewhere that can reach both APIs; SeekHunter's IP allowlist treats 192.168.4.106 as the
tunnel host, so run it on the SeekHunter box (192.168.4.50):

  python3 sync_watches.py \\
      --seekhunter http://127.0.0.1:8090 \\
      --changedetection http://192.168.4.106:5000 --api-key "$CD_API_KEY" \\
      --secret "$RADAR_WEBHOOK_SECRET" [--webhook-host 192.168.4.50:8090] \\
      [--fetch-backend html_webdriver] [--hours 2] [--update] [--dry-run]
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

# The webhook parses "watch_url: ..." and the added lines (see seekhunter.radar).
NOTIFICATION_TITLE = "SeekHunter radar: {{watch_title}}"
NOTIFICATION_BODY = "watch_url: {{watch_url}}\n{{diff_added}}"


def _request(method: str, url: str, headers: dict | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/json", **({"Content-Type": "application/json"} if data else {}),
        **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def norm(url: str) -> str:
    u = url.strip().lower()
    for prefix in ("https://", "http://"):
        u = u.removeprefix(prefix)
    return u.removeprefix("www.").split("#")[0].rstrip("/")


def webhook_url(host: str, secret: str) -> str:
    # apprise json:// -> POST http://host/path; "+Header=value" adds a request header. The secret
    # goes in both the X-Radar-Secret header and the query string (the webhook accepts either).
    q = urllib.parse.urlencode({"+X-Radar-Secret": secret, "secret": secret})
    return f"json://{host}/api/radar/webhook/changedetection?{q}"


def watch_body(company: dict, notify_url: str, fetch_backend: str, hours: int) -> dict:
    return {
        "url": company["careers_url"],
        "title": f"{company['name']} careers",
        "time_between_check": {"hours": hours},
        "fetch_backend": fetch_backend,
        "notification_urls": [notify_url],
        "notification_title": NOTIFICATION_TITLE,
        "notification_body": NOTIFICATION_BODY,
        "notification_format": "Text",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seekhunter", default="http://127.0.0.1:8090")
    ap.add_argument("--changedetection", default="http://192.168.4.106:5000")
    ap.add_argument("--api-key", required=True, help="changedetection.io API key (Settings -> API)")
    ap.add_argument("--secret", required=True, help="RADAR_WEBHOOK_SECRET from SeekHunter's .env")
    ap.add_argument("--webhook-host", default="192.168.4.50:8090")
    ap.add_argument("--fetch-backend", default="html_requests", choices=["html_requests", "html_webdriver"])
    ap.add_argument("--hours", type=int, default=2, help="check interval")
    ap.add_argument("--update", action="store_true", help="also rewrite settings of existing watches")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    companies = _request("GET", f"{args.seekhunter.rstrip('/')}/api/radar/companies?enabled=true")
    wanted = [c for c in companies if c.get("ats") in ("other", "pageup") and c.get("careers_url")]
    cd = args.changedetection.rstrip("/")
    headers = {"x-api-key": args.api_key}
    existing = {norm(w.get("url") or ""): uuid for uuid, w in (_request("GET", f"{cd}/api/v1/watch",
                                                                         headers) or {}).items()}
    notify = webhook_url(args.webhook_host, args.secret)
    created = updated = skipped = 0
    for c in wanted:
        body = watch_body(c, notify, args.fetch_backend, args.hours)
        uuid = existing.get(norm(c["careers_url"]))
        if uuid and not args.update:
            skipped += 1
            continue
        print(f"{'update' if uuid else 'create'}: {c['name']} -> {c['careers_url']}")
        if args.dry_run:
            continue
        try:
            if uuid:
                _request("PUT", f"{cd}/api/v1/watch/{uuid}", headers, body)
                updated += 1
            else:
                _request("POST", f"{cd}/api/v1/watch", headers, body)
                created += 1
        except urllib.error.HTTPError as e:
            print(f"  failed: HTTP {e.code} {e.read()[:200]!r}", file=sys.stderr)
    print(json.dumps({"companies": len(wanted), "created": created, "updated": updated,
                      "skipped": skipped}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
