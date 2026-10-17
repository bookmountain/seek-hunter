#!/usr/bin/env bash
set -euo pipefail
cd /opt/seek-hunter/app/backend

# Tectonic (LaTeX engine for resume tailoring): static musl build, installed once.
install_tectonic() {
  local url tmp bin
  url="$(curl -fsSL "https://api.github.com/repos/tectonic-typesetting/tectonic/releases?per_page=30" | python3 -c '
import json, sys
releases = json.load(sys.stdin)
releases.sort(key=lambda r: r.get("tag_name") != "continuous")  # prefer the continuous build
for r in releases:
    for a in r.get("assets", []):
        if a["name"].endswith("x86_64-unknown-linux-musl.tar.gz"):
            print(a["browser_download_url"]); sys.exit(0)
sys.exit(1)')" || return 1
  tmp="$(mktemp -d)"
  curl -fsSL "$url" | tar -xz -C "$tmp" || { rm -rf "$tmp"; return 1; }
  bin="$(find "$tmp" -type f -name tectonic | head -n1)"
  [ -n "$bin" ] && install -m 755 "$bin" /usr/local/bin/tectonic
  rm -rf "$tmp"
  /usr/local/bin/tectonic --version
}
if ! /usr/local/bin/tectonic --version >/dev/null 2>&1; then
  echo "installing tectonic"
  install_tectonic || echo "WARN: tectonic install failed; resume tailoring will not compile"
fi

/root/.local/bin/uv sync --frozen --no-dev
install -m 755 /opt/seek-hunter/app/deploy/bin/seekhunter-api /usr/local/bin/seekhunter-api
openclaw skills install /opt/seek-hunter/app/openclaw-skill/seekhunter --as seekhunter --force --agent main \
  --acknowledge-install-policy-warning || echo "WARN: openclaw skill install failed"
install -m 644 /opt/seek-hunter/app/deploy/systemd/*.service /opt/seek-hunter/app/deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now seekhunter-crawl.timer seekhunter-recap.timer seekhunter-market.timer \
  seekhunter-insights-brief.timer
systemctl enable seekhunter-web.service
systemctl restart seekhunter-web.service
# Build/cache the current resume preview once in the background. The first Tectonic run downloads its
# bundle (~3 min, cached in /root/.cache/tectonic), so never block the deploy on it.
warm_resume_preview() {
  systemctl reset-failed seekhunter-resume-preview.service >/dev/null 2>&1 || true
  systemd-run --no-block --collect --unit=seekhunter-resume-preview \
    -p EnvironmentFile=/opt/seek-hunter/.env -p WorkingDirectory=/opt/seek-hunter/app/backend \
    -p Environment=HOME=/root -p Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin \
    /root/.local/bin/uv run --frozen --no-dev seekhunter resume-preview >/dev/null 2>&1 \
    || echo "WARN: could not start resume preview warm-up"
}
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8090/api/health >/dev/null; then
    echo "healthy"
    warm_resume_preview
    exit 0
  fi
  sleep 1
done
journalctl -u seekhunter-web -n 80 --no-pager
exit 1
