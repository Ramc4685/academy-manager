#!/usr/bin/env bash
# Start the apt-installed mongod in the background on 127.0.0.1:27017 and wait
# until it answers a ping. CI uses this instead of a `services:` mongo container
# because the mongo:8.0 Docker image exits at startup on the ubuntu-26.04 runner
# kernel (SERVER-121912); the native 8.0.34 package does not.
set -euo pipefail

dbpath="${RUNNER_TEMP:-/tmp}/mongo-db"
logpath="${RUNNER_TEMP:-/tmp}/mongod.log"
mkdir -p "${dbpath}"

mongod --dbpath "${dbpath}" --bind_ip 127.0.0.1 --port 27017 --fork --logpath "${logpath}"

for _ in $(seq 1 30); do
  if mongosh --quiet --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1; then
    mongod --version | head -1
    exit 0
  fi
  sleep 1
done

echo "::error::mongod did not answer a ping within 30s"
tail -50 "${logpath}"
exit 1
