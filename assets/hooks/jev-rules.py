#!/usr/bin/env python3
"""PreToolUse hook: block edits and commits that break a hard rule from CLAUDE.md.

Rules live in .claude/jev-rules.json. Before each Edit/Write/MultiEdit, the rules
whose 'paths' match the file are sent to Jev in one call, one yes/no question per
rule. Before `git commit`, the staged diff is checked against the 'commit' rules.

  probability >= BLOCK (0.8)  -> deny, quoting the rule (Claude sees the reason)
  WARN (0.5) .. BLOCK         -> allow, with a note to Claude to double-check
  otherwise, or Jev failed    -> allow silently (fail open)

A rule blocks the same file at most twice per session, then only warns, so an
unfixable false positive can't trap Claude in a loop.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jev import ask, probability  # noqa: E402

BLOCK = float(os.environ.get("JEV_RULES_BLOCK", "0.8"))
WARN = float(os.environ.get("JEV_RULES_WARN", "0.5"))
MAX_BLOCKS = 2
MAX_CHARS = 12000


def load_rules(project):
    with open(os.path.join(project, ".claude", "jev-rules.json")) as f:
        return json.load(f)["rules"]


def edit_state(tool, inp, rel):
    if tool == "Write":
        change = {"new_file_content": inp.get("content", "")[:MAX_CHARS]}
    elif tool == "MultiEdit":
        change = {"edits": [{"old": e.get("old_string", "")[:2000], "new": e.get("new_string", "")[:2000]} for e in inp.get("edits", [])][:10]}
    else:
        change = {"old": inp.get("old_string", "")[:MAX_CHARS // 2], "new": inp.get("new_string", "")[:MAX_CHARS // 2]}
    return {"file": rel, "tool": tool, "change": change}


def commit_state(project):
    def git(*args):
        return subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, timeout=10).stdout
    return {"staged_files": git("diff", "--cached", "--name-status"), "staged_diff": git("diff", "--cached")[:MAX_CHARS]}


def blocks_so_far(session, key, bump=False):
    path = os.path.join(tempfile.gettempdir(), f"jev-rules-{session}.json")
    try:
        counts = json.load(open(path))
    except (OSError, ValueError):
        counts = {}
    if bump:
        counts[key] = counts.get(key, 0) + 1
        json.dump(counts, open(path, "w"))
    return counts.get(key, 0)


def main():
    data = json.load(sys.stdin)
    tool = data.get("tool_name")
    inp = data.get("tool_input") or {}
    project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or "."
    rules = load_rules(project)

    if tool in ("Edit", "Write", "MultiEdit"):
        rel = os.path.relpath(inp.get("file_path", ""), project)
        applicable = [r for r in rules if r["on"] == "edit" and re.search(r.get("paths", ""), rel)]
        target = rel
        state = lambda: edit_state(tool, inp, rel)  # noqa: E731
    elif tool == "Bash" and re.search(r"\bgit\b.*\bcommit\b", inp.get("command", "")):
        applicable = [r for r in rules if r["on"] == "commit"]
        target = "commit"
        state = lambda: commit_state(project)  # noqa: E731
    else:
        return
    if not applicable:
        return

    questions = {
        r["id"]: {"type": "boolean", "instructions": f"Does this change break the following rule? Rule: {r['rule']}"}
        for r in applicable
    }
    answers = ask(state(), questions)
    if answers is None:
        return

    session = data.get("session_id", "nosession")
    broken, unsure = [], []
    for r in applicable:
        p = probability(answers, r["id"])
        if p is None:
            continue
        key = f"{r['id']}::{target}"
        if p >= BLOCK and blocks_so_far(session, key) < MAX_BLOCKS:
            blocks_so_far(session, key, bump=True)
            broken.append((r, p))
        elif p >= BLOCK:
            unsure.append((r, p, "already blocked twice this session, letting it through"))
        elif p >= WARN:
            unsure.append((r, p, "unsure"))

    if broken:
        lines = [f"- \"{r['rule']}\" ({r['source']}, Jev {p:.2f})" for r, p in broken]
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Blocked by the Jev rule check. This change breaks:\n" + "\n".join(lines)
            + "\nRedo it in a way that follows the rule. If you're sure this is a false positive, tell the user which rule and why.",
        }}))
    elif unsure:
        lines = [f"- \"{r['rule']}\" ({r['source']}, Jev {p:.2f}, {why})" for r, p, why in unsure]
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "Jev rule check flagged, without blocking, whether this change follows:\n" + "\n".join(lines) + "\nDouble-check it.",
        }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open
