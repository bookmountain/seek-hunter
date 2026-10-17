#!/usr/bin/env bash
set -euo pipefail
command -v rsync >/dev/null || apt-get install -y rsync
if [ ! -x /root/.local/bin/uv ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
/root/.local/bin/uv python install 3.12
mkdir -p /opt/seek-hunter/{app,data,book-cv}
if [ ! -f /opt/seek-hunter/.env ]; then
  sed "s/^API_WRITE_TOKEN=.*/API_WRITE_TOKEN=$(openssl rand -hex 24)/" /tmp/seekhunter-env.example > /opt/seek-hunter/.env
  chmod 600 /opt/seek-hunter/.env
  echo "Created /opt/seek-hunter/.env (add ANTHROPIC_API_KEY)"
fi
echo "bootstrap done"
