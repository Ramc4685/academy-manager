#!/usr/bin/env bash
# Docker dev entrypoint: wait for Mongo → seed if empty → start uvicorn.
set -e

MONGO_URL="${MONGO_URL:-${V2_MONGO_URL:-mongodb://mongo:27017}}"
MONGO_DB="${V2_MONGO_DB:-${DB_NAME:-academy_manager}}"
export PYTHONPATH="/app:/app/backend"

echo "==> Waiting for MongoDB at $MONGO_URL ..."
until python3 -c "
from pymongo import MongoClient
MongoClient('$MONGO_URL', serverSelectionTimeoutMS=2000).admin.command('ping')
" 2>/dev/null; do
  sleep 1
done
echo "==> MongoDB ready."

# ── Main seed (blno data) ───────────────────────────────────────────────────
DOC_COUNT=$(python3 -c "
from pymongo import MongoClient
print(MongoClient('$MONGO_URL')['$MONGO_DB']['academies'].count_documents({}))
" 2>/dev/null || echo "0")

if [ "$DOC_COUNT" = "0" ]; then
  echo "==> Empty database — running main seed ..."
  cd /app && python3 backend/scripts/seed_local.py
  echo "==> Main seed done."
else
  echo "==> Database already seeded ($DOC_COUNT academy records) — skipping main seed."
fi

# ── Curriculum / skill pathway seed ────────────────────────────────────────
SKILL_COUNT=$(python3 -c "
from pymongo import MongoClient
print(MongoClient('$MONGO_URL')['$MONGO_DB']['curriculum_skills'].count_documents({}))
" 2>/dev/null || echo "0")

if [ "$SKILL_COUNT" = "0" ]; then
  echo "==> No skills found — running curriculum seed ..."
  cd /app && python3 backend/scripts/seed_skills_dev.py
  echo "==> Curriculum seed done."
else
  echo "==> Curriculum already seeded ($SKILL_COUNT skills) — skipping."
fi

# ── Firebase emulator user seed (always runs; idempotent) ──────────────────
if [ -n "${FIREBASE_AUTH_EMULATOR_HOST:-}" ]; then
  echo "==> Ensuring Firebase emulator users exist ..."
  cd /app && python3 backend/scripts/seed_firebase_users.py
fi

echo "==> Starting uvicorn ..."
exec uvicorn backend.v2.main:app --host 0.0.0.0 --port 8001
