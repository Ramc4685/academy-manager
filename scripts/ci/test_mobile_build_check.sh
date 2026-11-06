#!/usr/bin/env bash
# Self-check for mobile_build_check.sh in a throwaway git repo (no real tags touched).
set -euo pipefail

check="$(cd "$(dirname "$0")" && pwd)/mobile_build_check.sh"
repo=$(mktemp -d)
trap 'rm -rf "$repo"' EXIT
cd "$repo"
git init -q
git config user.email ci@example.com
git config user.name ci
commit() { mkdir -p "$(dirname "$1")"; echo "$RANDOM" >>"$1"; git add -A; git commit -qm "$1"; }
expect() { grep -qF -- "$1" <<<"$out" || { echo "FAIL: expected '$1' in:"; echo "$out"; exit 1; }; }

commit mobile/capacitor.config.ts
out=$("$check")
expect "iOS: no baseline yet"
expect "Mobile build status unknown (no build tag yet for iOS Android)"

git tag ios-build-5
git tag android-build-1
commit frontend/app/page.tsx
commit mobile/SPIKE.md
out=$("$check")
expect "iOS: no build needed"
expect "Android: no build needed"
expect "**No mobile build needed.**"

commit mobile/android/app/build.gradle
out=$("$check")
expect "iOS: no build needed"
expect "Android: build needed.** 1 native file(s) changed since \`android-build-1\`"
expect "Mobile build needed: Android."

git tag android-build-2
git tag ios-build-10 HEAD~1
commit mobile/ios/App/App/Info.plist
out=$("$check")
expect "since \`ios-build-10\`"
expect "mobile/ios/App/App/Info.plist"
expect "Android: no build needed.** Native shell unchanged since \`android-build-2\`"
expect "Mobile build needed: iOS."

echo "mobile_build_check: all cases pass"
