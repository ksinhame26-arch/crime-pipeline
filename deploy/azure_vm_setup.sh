#!/usr/bin/env bash
# azure_vm_setup.sh - deploy the whole crime pipeline on a fresh Ubuntu VM.
#   sudo bash azure_vm_setup.sh [repo-url]
# 1. installs Docker   2. clones the repo to /opt/crime-pipeline
# 3. creates .env (random passwords) unless /opt/crime-pipeline/.env or /root/crime.env exists
# 4. starts Postgres, Metabase, Prefect server and the scheduled ETL container
# 5. runs the ETL once (first load)  6. builds the Metabase dashboard + public link
set -euo pipefail
REPO="${1:-https://github.com/ksinhame26-arch/crime-pipeline.git}"
APP=/opt/crime-pipeline
log() { echo "[crime-pipeline] $*"; }

log "1/6 Installing Docker"
if ! command -v docker >/dev/null; then
  apt-get update -y && apt-get install -y ca-certificates curl git python3
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

log "2/6 Getting the code"
if [ -d "$APP/.git" ]; then git -C "$APP" pull --ff-only; else git clone "$REPO" "$APP"; fi
cd "$APP"

log "3/6 Preparing .env"
if [ ! -f .env ]; then
  if [ -f /root/crime.env ]; then
    cp /root/crime.env .env
  else
    rnd() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20; }
    cp .env.example .env
    sed -i "s/change_me_strong_password/$(rnd)/; s/change_me_too/$(rnd)/; s/change_me_three/$(rnd)/; s/change_me_four/$(rnd)A9/" .env
    sed -i "s/^SOCRATA_APP_TOKEN=.*/SOCRATA_APP_TOKEN=/" .env
  fi
  sed -i "s/^DEPLOYMENT_NAME=.*/DEPLOYMENT_NAME=cpd-pipeline-azure/" .env
  chmod 600 .env
fi

log "4/6 Starting containers"
docker compose --profile etl up -d --build

log "5/6 First data load"
for i in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' postgres_cpd 2>/dev/null)" = healthy ] && break; sleep 5
done
docker compose run --rm etl python etl_pipeline.py --once

log "6/6 Metabase dashboard + public link"
PUBLIC_IP=$(curl -s -H Metadata:true --max-time 5 \
  "http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01&format=text" || true)
[ -z "$PUBLIC_IP" ] && PUBLIC_IP=$(curl -s --max-time 5 https://api.ipify.org || echo localhost)
python3 deploy/metabase_bootstrap.py --url http://localhost:3000 --public-base "http://$PUBLIC_IP:3000"

docker compose ps
log "DONE. Public dashboard: $(cat PUBLIC_DASHBOARD_LINK.txt)"
