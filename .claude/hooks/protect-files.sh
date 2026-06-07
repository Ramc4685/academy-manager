#!/usr/bin/env bash
set -euo pipefail

hook_input="$(cat)"

HOOK_INPUT="${hook_input}" python3 - <<'PY'
import json
import os
import re
import sys

try:
    payload = json.loads(os.environ.get("HOOK_INPUT", "{}"))
except json.JSONDecodeError:
    sys.exit(0)

tool_input = payload.get("tool_input") or {}
paths: list[str] = []

for key in ("file_path", "path"):
    value = tool_input.get(key)
    if isinstance(value, str):
        paths.append(value)

for edit in tool_input.get("edits") or []:
    if isinstance(edit, dict):
        value = edit.get("file_path") or edit.get("path")
        if isinstance(value, str):
            paths.append(value)

protected_patterns = [
    r"(^|/)\.env($|\.)",
    r"(^|/).*credentials.*\.json$",
    r"(^|/).*service[-_]?account.*\.json$",
    r"(^|/).*token.*\.json$",
    r"\.(pem|key|p12|pfx)$",
    r"(^|/)pnpm-lock\.yaml$",
    r"(^|/)package-lock\.json$",
    r"(^|/)yarn\.lock$",
    r"(^|/)poetry\.lock$",
    r"(^|/)Pipfile\.lock$",
]

for candidate in paths:
    normalized = candidate.replace(os.sep, "/")
    for pattern in protected_patterns:
        if re.search(pattern, normalized, re.IGNORECASE):
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": (
                                f"Direct edits to protected file '{candidate}' are blocked. "
                                "Use the relevant package manager, secret manager, or ask for explicit override."
                            ),
                        }
                    }
                )
            )
            sys.exit(0)

sys.exit(0)
PY
