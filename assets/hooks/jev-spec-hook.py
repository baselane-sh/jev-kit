#!/usr/bin/env python3
"""PostToolUse hook: after an edit to a spec, or to code a spec covers, have Jev check that
spec's rules for tests, and tell Claude about any gaps (exit 2 -> Claude sees stderr).

Specs and the code paths they cover ('watch', a regex) come from .claude/jev-spec.json.
Reports each spec at most once per session; editing the spec itself re-arms it.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "jev-spec-check"))
from check import COVERED, load_config, run  # noqa: E402


def main():
    data = json.load(sys.stdin)
    project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or "."
    rel = os.path.relpath((data.get("tool_input") or {}).get("file_path", ""), project)
    specs = [s["spec"] for s in load_config(project).get("specs", [])
             if rel == os.path.normpath(s["spec"]) or (s.get("watch") and re.search(s["watch"], rel))]
    if not specs:
        return 0

    seen_file = Path(tempfile.gettempdir(), f"jev-spec-{data.get('session_id', 'x')}.json")
    try:
        seen = set(json.loads(seen_file.read_text()))
    except (OSError, ValueError):
        seen = set()
    todo = [(s, f"{s}@{os.path.getmtime(Path(project, s))}") for s in specs]
    todo = [(s, key) for s, key in todo if key not in seen]
    if not todo:
        return 0

    missing, total = [], 0
    for spec, key in todo:
        rows = run(project, spec)
        if rows is None:
            return 0  # fail open
        seen.add(key)
        total += len(rows)
        missing += [r for r in rows if (r["p_covered"] or 0) < COVERED]
    seen_file.write_text(json.dumps(sorted(seen)))
    if not missing:
        return 0
    lines = "\n".join(f"- [{r['spec']} § {r['section']}] {r['rule']}" for r in missing[:25])
    print(
        f"Jev spec check: {len(missing)} of {total} rules have no test:\n{lines}\n"
        "Tell the user, and offer to write them with /jev-spec-check.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open
