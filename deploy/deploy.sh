#!/usr/bin/env bash
set -euo pipefail
cd /opt/seek-hunter/app/backend
/root/.local/bin/uv sync --frozen --no-dev
install -m 755 /opt/seek-hunter/app/deploy/bin/seekhunter-api /usr/local/bin/seekhunter-api
openclaw skills install /opt/seek-hunter/app/openclaw-skill/seekhunter --as seekhunter --force \
  --acknowledge-install-policy-warning || echo "WARN: openclaw skill install failed"
install -m 644 /opt/seek-hunter/app/deploy/systemd/*.service /opt/seek-hunter/app/deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now seekhunter-crawl.timer seekhunter-recap.timer
systemctl enable seekhunter-web.service
systemctl restart seekhunter-web.service
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8090/api/health >/dev/null; then echo "healthy"; exit 0; fi
  sleep 1
done
journalctl -u seekhunter-web -n 80 --no-pager
exit 1
