#!/bin/sh
# Removes the dev-only `localhost` entry from WKAppBoundDomains in a BUILT Info.plist.
# The Xcode "Strip dev App-Bound Domains" phase runs it for Release builds only, so the
# source ios/App/App/Info.plist keeps localhost for simulator runs against `next dev`.
# Usage: strip-dev-bound-domains.sh <path/to/Info.plist>
set -eu
plist="$1"
buddy=/usr/libexec/PlistBuddy
i=0
while value=$("$buddy" -c "Print :WKAppBoundDomains:$i" "$plist" 2>/dev/null); do
  if [ "$value" = localhost ]; then
    "$buddy" -c "Delete :WKAppBoundDomains:$i" "$plist"
  else
    i=$((i + 1))
  fi
done
