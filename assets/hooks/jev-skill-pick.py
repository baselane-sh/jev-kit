#!/usr/bin/env python3
"""UserPromptSubmit hook: Jev picks which project skill fits the prompt, or none.

Reads the name and description of every skill in .claude/skills/*/SKILL.md, asks
Jev one choice question, and when the pick is confident tells Claude which skill
to use. Unsure, "none", slash commands and any Jev failure add nothing.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jev import ask, choice  # noqa: E402

THRESHOLD = float(os.environ.get("JEV_SKILL_THRESHOLD", "0.6"))
NONE_OPTION = "none"


def skills(project):
    found = {}
    for md in sorted(Path(project, ".claude", "skills").glob("*/SKILL.md")):
        head = re.match(r"---\s*\n(.*?)\n---", md.read_text(errors="replace"), re.S)
        front = head.group(1) if head else ""
        name = re.search(r"^name:\s*(.+)$", front, re.M)
        # Take indented continuation lines too, so YAML block scalars (description: >) work.
        desc = re.search(r"^description:[ \t]*(.*(?:\n[ \t]+.*)*)", front, re.M)
        if name and desc:
            text = " ".join(re.sub(r"^[>|][-+]?", "", desc.group(1).strip()).split()).strip("\"'")
            found[name.group(1).strip().strip("\"'")] = text[:600]
    return found


def main():
    data = json.load(sys.stdin)
    prompt = (data.get("prompt") or "").strip()
    if not prompt or prompt.startswith("/"):
        return
    project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or "."
    roster = skills(project)
    if not roster:
        return
    criteria = dict(roster)
    criteria[NONE_OPTION] = "The request doesn't need any of these skills: a question, a small edit, or anything the skills above don't cover."
    answers = ask(
        {"user_request": prompt[:4000]},
        {"skill": {"type": "choice", "instructions": "Which skill should handle this request, if any?", "criteria": criteria}},
    )
    picked, p = choice(answers, "skill")
    if not picked or picked == NONE_OPTION or p is None or p < THRESHOLD:
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": f"Jev skill pick ({p:.2f}): this request fits the `{picked}` skill. Read .claude/skills/{picked}/SKILL.md and follow it.",
    }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open: never block a prompt
