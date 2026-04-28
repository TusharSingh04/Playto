#!/usr/bin/env bash
# Render build script — runs once per deploy on every backend service
# (api, worker, beat). Idempotent.
set -o errexit  # exit on any non-zero
set -o pipefail
set -o nounset

cd backend

echo "── Installing Python deps ─────────────────────────────────────────"
pip install --upgrade pip
pip install -r requirements.txt

echo "── Collecting static files ────────────────────────────────────────"
python manage.py collectstatic --noinput

echo "── Running migrations ─────────────────────────────────────────────"
python manage.py migrate --noinput

# Seed only on the first deploy (safe: get_or_create everywhere).
# Set SEED_ON_DEPLOY=false in env to skip on subsequent deploys.
if [ "${SEED_ON_DEPLOY:-true}" = "true" ]; then
  echo "── Seeding demo merchants + tokens ───────────────────────────────"
  python manage.py seed_data
fi

echo "── Build complete ─────────────────────────────────────────────────"
