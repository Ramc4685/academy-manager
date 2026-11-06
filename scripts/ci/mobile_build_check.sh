#!/usr/bin/env bash
# Says whether the native mobile shell changed since the last store build.
#
# The apps load the live site (server.url), so only mobile/ changes need a new
# TestFlight / Play build. Each upload is marked with a tag, ios-build-<n> or
# android-build-<n> (see docs/runbooks/mobile-store-builds.md). For each
# platform this diffs mobile/ from its newest tag to HEAD, ignoring the other
# platform's folder and Markdown files.
#
# Usage: scripts/ci/mobile_build_check.sh [ref]   (default HEAD)
# Prints Markdown. Information only: always exits 0 unless git itself fails.
set -euo pipefail

ref=${1:-HEAD}
needed=()
missing=()

echo "## Mobile store build check"
echo
for platform in ios android; do
  if [ "$platform" = ios ]; then other=android; label=iOS; else other=ios; label=Android; fi
  tag=$(git tag -l "${platform}-build-*" --sort=-v:refname | head -n1)
  if [ -z "$tag" ]; then
    echo "- **${label}: no baseline yet.** No \`${platform}-build-<n>\` tag exists, so CI cannot tell what the last store build contained. Tag the commit of the last upload (docs/runbooks/mobile-store-builds.md)."
    missing+=("$label")
    continue
  fi
  changed=$(git diff --name-only "$tag" "$ref" -- mobile \
    ":(exclude)mobile/${other}" ':(exclude,glob)mobile/**/*.md')
  if [ -z "$changed" ]; then
    echo "- **${label}: no build needed.** Native shell unchanged since \`${tag}\`."
  else
    needed+=("$label")
    echo "- **${label}: build needed.** $(wc -l <<<"$changed" | tr -d ' ') native file(s) changed since \`${tag}\`:"
    while IFS= read -r file; do echo "  - \`${file}\`"; done <<<"$changed"
  fi
done

echo
if [ ${#needed[@]} -gt 0 ]; then
  verdict="Mobile build needed: ${needed[*]}"
elif [ ${#missing[@]} -lt 2 ]; then
  verdict="No mobile build needed"
else
  verdict="Mobile build status unknown"
fi
if [ ${#missing[@]} -gt 0 ]; then
  verdict="${verdict} (no build tag yet for ${missing[*]})"
fi
echo "**${verdict}.** Web-only changes reach installed apps on deploy."
if [ -n "${GITHUB_ACTIONS:-}" ]; then
  echo "::notice title=Mobile store build::${verdict}" >&2
fi
