#!/usr/bin/env python3
"""Rank the repo's source files by relevance to a question, using Jev.

    python3 .claude/skills/jev-explore/jev_rank.py "where are refunds approved?" [--grep REGEX] [--top 5]

1. Candidates: tracked source files (git ls-files), narrowed by --grep if given.
2. Each candidate becomes a short preview: path, first 40 lines, and any lines matching --grep.
3. Jev answers one yes/no per file ("is this where <question> is handled?"), in batches
   of 20 files per call, batches in parallel.
4. Prints the top N by probability. Exit 1 if Jev couldn't be reached.
"""
import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "hooks")
sys.path.insert(0, os.path.abspath(HOOKS))
from jev import ask, probability  # noqa: E402

SOURCE = re.compile(os.environ.get(
    "JEV_EXPLORE_EXT",
    r"\.(py|ts|tsx|js|jsx|mjs|cjs|vue|svelte|go|rs|java|kt|swift|rb|php|cs|c|cc|cpp|h|hpp|scala|ex|exs|sql|sh)$",
))
BATCH = 20
PREVIEW_LINES = 40
PREVIEW_CHARS = 1500


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.splitlines()


def candidates(pattern):
    files = [f for f in git("ls-files") if SOURCE.search(f) and "node_modules" not in f and not f.startswith(".claude/")]
    if pattern:
        hits = set(git("grep", "-l", "-i", "-E", pattern))  # no pathspec: a big repo's file list overflows argv
        files = [f for f in files if f in hits]
    return files


def preview(path, pattern):
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return ""
    text = "\n".join(lines[:PREVIEW_LINES])
    if pattern:
        rx = re.compile(pattern, re.I)
        extra = [f"{i + 1}: {l}" for i, l in enumerate(lines[PREVIEW_LINES:], PREVIEW_LINES) if rx.search(l)][:10]
        if extra:
            text += "\n... matching lines:\n" + "\n".join(extra)
    return text[:PREVIEW_CHARS]


def rank_batch(question, batch, pattern):
    state = {f"file_{i}": {"path": p, "preview": preview(p, pattern)} for i, p in enumerate(batch)}
    questions = {
        f"file_{i}": {"type": "boolean", "instructions": f"Is {p} (state key file_{i}) a file where this is handled or defined: {question}"}
        for i, p in enumerate(batch)
    }
    answers = ask(state, questions, timeout=15)
    if answers is None:
        return None
    return [(p, probability(answers, f"file_{i}") or 0.0) for i, p in enumerate(batch)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--grep", default="")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    files = candidates(args.grep)
    if not files:
        print("No candidate files. Try a broader --grep.")
        return 0
    started = time.time()
    batches = [files[i:i + BATCH] for i in range(0, len(files), BATCH)]
    with ThreadPoolExecutor(max_workers=int(os.environ.get("JEV_PARALLEL", "4"))) as pool:
        results = list(pool.map(lambda b: rank_batch(args.question, b, args.grep), batches))
    if any(r is None for r in results):
        print("Jev couldn't be reached (check AI_GATEWAY_API_KEY). Fall back to normal search.")
        return 1
    ranked = sorted((x for r in results for x in r), key=lambda x: -x[1])
    print(f"Jev ranked {len(files)} files in {time.time() - started:.1f}s ({len(batches)} call(s)). Top {args.top}:")
    for path, p in ranked[:args.top]:
        print(f"  {p:.2f}  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
