#!/usr/bin/env bash
# Run the persona-kit seeds (kNN_*.js) against a LOCAL Mongo. Never CI or deploy.
# Usage: scripts/dev/persona_kit/run.sh [k01 k05 ...]   (no args = every kit, in order)
set -euo pipefail

MONGO_URL="${MONGO_URL:-mongodb://127.0.0.1:27017}"
DB_NAME="${DB_NAME:-academy_manager_local}"
here="$(cd "$(dirname "$0")" && pwd)"

# Host = text after the scheme and any credentials, up to the first port/path/query.
rest="${MONGO_URL#mongodb://}"
if [[ "$rest" == "$MONGO_URL" ]]; then
  echo "refusing: MONGO_URL must start with mongodb:// (got a non-local scheme)" >&2
  exit 2
fi
rest="${rest##*@}"
host="${rest%%[:/?]*}"
if [[ "$rest" == *,* || ( "$host" != "127.0.0.1" && "$host" != "localhost" ) ]]; then
  echo "refusing: persona kit only runs against 127.0.0.1 or localhost (got '$host')" >&2
  exit 2
fi

files=()
if [[ $# -eq 0 ]]; then
  files=("$here"/k[0-9][0-9]_*.js)
else
  for kit in "$@"; do
    id="$(echo "$kit" | tr '[:upper:]' '[:lower:]')"
    match=("$here"/"$id"_*.js)
    [[ -e "${match[0]}" ]] || { echo "no kit named $kit" >&2; exit 2; }
    files+=("${match[@]}")
  done
fi

for f in "${files[@]}"; do
  echo "== $(basename "$f")"
  mongosh --quiet "${MONGO_URL%/}/$DB_NAME" "$f"
done
