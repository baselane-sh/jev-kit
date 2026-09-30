#!/usr/bin/env python3
"""Check that every rule in a spec doc has a test, using Jev as the judge.

    python3 .claude/skills/jev-spec-check/check.py [--spec docs/PERMISSIONS.md] [--section Billing] [--json]

Specs and the test-file pattern come from .claude/jev-spec.json. Every list item and
table row in a spec is one rule, grouped under its nearest heading. For each section,
Jev gets that section's rules plus the test files that share words with them, and
answers one yes/no per rule: is there a test that checks this?

Jev only judges whether a test exists. Running the tests decides whether they pass.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[2] / "hooks"
sys.path.insert(0, str(HOOKS))
from jev import ask, probability  # noqa: E402

COVERED = 0.5
MIN_RULE_CHARS = 12
PER_CALL = 25
FILE_CHARS = 6000
EVIDENCE_CHARS = 60000
DEFAULT_TESTS = r"(^|/)(tests?|__tests__|spec)/|[._-](test|spec)\.\w+$|(^|/)test_[^/]+\.py$"
SKIP_DIRS = {".git", ".claude", "node_modules", ".venv", "venv", "dist", "build", ".next", "__pycache__"}
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")


def load_config(project):
    try:
        with open(Path(project, ".claude", "jev-spec.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def parse_rules(text):
    """-> {section: [rule]} from list items and table rows, keyed by the nearest heading."""
    sections, current, header = {}, "(top)", None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        h = re.match(r"^#{1,6}\s+(.+)", s)
        if h:
            current, header = h.group(1).strip(), None
            continue
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # separator row
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if re.match(r"^\|?\s*:?-{2,}", nxt):
                header = cells
                continue
            if header and len(header) == len(cells):
                rule = "; ".join(f"{h}: {c}" for h, c in zip(header, cells))
            else:
                rule = " | ".join(cells)
        else:
            m = re.match(r"^(?:[-*+]|\d+[.)])\s+(.+)", s)
            if not m:
                continue
            rule = m.group(1)
        if len(rule) >= MIN_RULE_CHARS:
            sections.setdefault(current, []).append(rule)
    return sections


def project_files(project):
    r = subprocess.run(["git", "ls-files"], cwd=project, capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.splitlines()
    out = []
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        out += [os.path.relpath(os.path.join(root, f), project) for f in files]
    return out


def read_tests(project, pattern):
    rx = re.compile(pattern)
    out = {}
    for f in project_files(project):
        if rx.search(f) and not f.startswith(".claude/"):
            try:
                out[f] = Path(project, f).read_text(errors="replace")
            except OSError:
                pass
    return out


def evidence_for(rules, tests):
    """Test files that share the most words with these rules, up to EVIDENCE_CHARS."""
    words = {w.lower() for r in rules for w in WORD.findall(r)}
    scored = sorted(((sum(w in src.lower() for w in words), f, src) for f, src in tests.items()), key=lambda x: -x[0])
    out, size = [], 0
    for hits, f, src in scored:
        chunk = f"# {f}\n{src[:FILE_CHARS]}"
        if not hits or size + len(chunk) > EVIDENCE_CHARS:
            break
        out.append(chunk)
        size += len(chunk)
    return "\n\n".join(out)


def check_chunk(spec, section, rules, tests):
    evidence = evidence_for(rules, tests) or "(no test file mentions these rules)"
    answers = ask(
        {"spec": spec, "section": section, "tests": evidence},
        {f"r{i}": {"type": "boolean", "instructions": f"Is there a test in `tests` that checks this rule? Rule: {r}"} for i, r in enumerate(rules)},
        timeout=20,
    )
    if answers is None:
        return None
    return [{"spec": spec, "section": section, "rule": r, "p_covered": probability(answers, f"r{i}")} for i, r in enumerate(rules)]


def run(project, spec=None, section=None):
    """-> list of {spec, section, rule, p_covered}, or None if Jev failed."""
    cfg = load_config(project)
    specs = [spec] if spec else [s["spec"] for s in cfg.get("specs", [])]
    tests = read_tests(project, cfg.get("tests", DEFAULT_TESTS))
    jobs = []
    for sp in specs:
        for name, rules in parse_rules(Path(project, sp).read_text(errors="replace")).items():
            if section and not name.lower().startswith(section.lower()):
                continue
            jobs += [(sp, name, rules[i:i + PER_CALL]) for i in range(0, len(rules), PER_CALL)]
    with ThreadPoolExecutor(max_workers=int(os.environ.get("JEV_PARALLEL", "4"))) as pool:
        results = list(pool.map(lambda j: check_chunk(*j, tests), jobs))
    if any(r is None for r in results):
        return None
    return [x for r in results for x in r]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", help="one spec file instead of every spec in .claude/jev-spec.json")
    ap.add_argument("--section", help="only sections whose heading starts with this")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    specs = [args.spec] if args.spec else [s["spec"] for s in load_config(project).get("specs", [])]
    if not specs:
        print("No specs configured. Add them to .claude/jev-spec.json or pass --spec.")
        return 1
    missing_specs = [s for s in specs if not Path(project, s).is_file()]
    if missing_specs:
        print(f"Spec file not found: {', '.join(missing_specs)}. Fix the path in .claude/jev-spec.json or --spec.")
        return 1
    rows = run(project, args.spec, args.section)
    if rows is None:
        print("Jev couldn't be reached (check AI_GATEWAY_API_KEY).")
        return 1
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    missing = [r for r in rows if (r["p_covered"] or 0) < COVERED]
    print(f"{len(rows)} rules checked, {len(rows) - len(missing)} have a test, {len(missing)} don't.\n")
    for r in missing:
        print(f"  MISSING  [{r['spec']} § {r['section']}] {r['rule']}  (Jev {r['p_covered'] or 0:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
