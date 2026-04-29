#!/usr/bin/env python3
"""
PreToolUse hook: rewrite bare python3/pytest to .venv equivalents.
No-op if .venv/bin/python3 does not exist.
"""
import json, os, re, sys

d = json.load(sys.stdin)
cmd = d.get("tool_input", {}).get("command", "")

if not os.path.exists(".venv/bin/python3"):
    sys.exit(0)

c2 = re.sub(r"(?<![/\w])python3(?![\w.])", ".venv/bin/python3", cmd)

def _repl_pytest(m):
    # Don't replace 'pytest' when used as a -m argument (e.g. python3 -m pytest)
    if c2[: m.start()].rstrip().endswith("-m"):
        return m.group(0)
    return ".venv/bin/pytest"

c2 = re.sub(r"(?<![/\w])pytest(?!\w)", _repl_pytest, c2)

if c2 == cmd:
    sys.exit(0)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "updatedInput": {"command": c2},
    }
}))
