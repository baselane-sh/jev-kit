#!/usr/bin/env python3
"""Cheap first pass before the adversarial review: Jev triages a diff against a fixed risk checklist.

    python3 .claude/skills/adversarial-loop/jev_triage.py [--base HEAD~1 | --commit SHA] [-- file1 file2 ...]

Asks Jev one yes/no per risk, all in one call. Prints one line the coordinator acts on:
  RISK: LOW                     every risk confidently "no"  -> light review (1 critic round)
  RISK: HIGH <risks>            any risk "yes" or unsure     -> full adversarial loop
  RISK: UNKNOWN                 Jev unreachable              -> full adversarial loop (fail safe)

These are triage questions ("does this touch money?"), not "is this code good?". The
adversarial reviewer still judges quality; Jev only decides how much review a change gets.
"""
import argparse
import os
import subprocess
import sys

HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "hooks")
sys.path.insert(0, os.path.abspath(HOOKS))
from jev import ask, probability  # noqa: E402

LOW = float(os.environ.get("JEV_TRIAGE_LOW", "0.2"))
MAX_DIFF = 60000

RISKS = {
    "auth": "Does this diff change authentication, authorization, roles, sessions, or who can call an endpoint or see a record?",
    "money": "Does this diff change how money, prices, payments, tax or amounts are calculated, rounded or stored?",
    "schema": "Does this diff add or change a database table, column, constraint, index or migration?",
    "data_loss": "Could this diff delete, overwrite or irreversibly change existing data?",
    "state": "Does this diff change a state transition (e.g. pending/approved/cancelled, draft/published) or concurrency handling?",
    "api_contract": "Does this diff change an existing API endpoint's request or response shape, or its status codes?",
    "secrets": "Does this diff add or expose secrets, keys, credentials or environment configuration?",
}


def diff(base, files):
    cmd = ["git", "diff", base, "--"] + files
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--"] + files,
                               capture_output=True, text=True).stdout.split()
    for f in untracked[:20]:
        try:
            out += f"\n+++ new file {f}\n" + open(f, errors="replace").read()[:5000]
        except OSError:
            pass
    return out[:MAX_DIFF]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--commit", help="triage one past commit instead of the working tree")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()
    if args.commit:
        shown = subprocess.run(["git", "show", "--format=", args.commit, "--"] + args.files,
                               capture_output=True, text=True)
        if shown.returncode:
            print(f"RISK: UNKNOWN (no such commit {args.commit}, run the full review)")
            return 1
        d = shown.stdout[:MAX_DIFF]
    else:
        d = diff(args.base, args.files)
    if not d.strip():
        print("RISK: LOW (empty diff)")
        return 0
    answers = ask({"diff": d}, {k: {"type": "boolean", "instructions": q} for k, q in RISKS.items()}, timeout=15)
    if answers is None:
        print("RISK: UNKNOWN (Jev unreachable, run the full review)")
        return 0
    probs = {k: probability(answers, k) for k in RISKS}
    hits = [f"{k}={p:.2f}" for k, p in probs.items() if p is None or p >= LOW]
    print("RISK: HIGH " + ", ".join(hits) if hits else "RISK: LOW " + ", ".join(f"{k}={p:.2f}" for k, p in probs.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
