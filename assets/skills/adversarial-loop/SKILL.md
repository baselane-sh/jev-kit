---
name: adversarial-loop
description: Review recent changes with a multi-round debate between two agents until the code is clean. Jev first triages the diff for risk, so low-risk changes get one quick critic round and risky ones get the full loop. adversarial-reviewer (the critic) assumes everything is wrong; fixer implements fixes or disputes them with evidence. They exchange findings through a shared thread file, and each keeps its memory across rounds. Use when the user asks for an adversarial review, a review-and-fix loop, or a hard review of recent changes (e.g. "/adversarial-loop", "have the critic and fixer go at this").
---

# Adversarial loop

You are the **coordinator**. You run in the main session because only the main session can start and resume agents; subagents can't launch other agents. You never review or fix the code yourself, and you **never read the thread file**. You pass turns between the two agents and act on their short returns.

## Setup

- **Scope:** by default, `git diff HEAD` plus untracked files. If the user names files, a commit range or a feature, use that. Call the file list `changed_files`.
- **Verify commands:** the project's own test, lint, typecheck and build commands. Find them in CLAUDE.md, the README, `package.json` scripts, the Makefile, `pyproject.toml` and so on. If you can't find them, ask the user.
- **Thread file:** `docs/reviews/<topic>-<YYYY-MM-DD>.md`. Create it with a header that holds the goal of the change (from the user or the commit messages), the acceptance criteria if there are any, `changed_files` and the verify commands. Nothing else.

## Jev pre-check (before round 1)

Run `python3 .claude/skills/adversarial-loop/jev_triage.py --base <base ref, default HEAD> -- <changed_files>`. It asks Jev a fixed risk checklist about the diff: auth, money, schema, data loss, state transitions, API contract, and secrets.

- `RISK: LOW`: run **one** critic round with no debate. If the critic returns PASS, you're done. If it finds anything, continue with the normal rounds below.
- `RISK: HIGH …` or `RISK: UNKNOWN`: run the full loop below, and put the flagged risks in the thread header so the critic starts there.

Record the triage line in the thread header.

## Rounds (at most 4)

1. **Critic, round 1:** start `adversarial-reviewer` with the scope, the thread path and "Debate mode, round 1". Keep its agent ID. If it returns `VERDICT: PASS`, you're done; go to the end.
2. **Fixer, round N:** start `fixer` with the thread path, the scope and "round N". On later rounds, resume the **same** fixer with SendMessage and its ID: "Round N: the critic has ruled, see the thread." Add its `FILES` to `changed_files`.
3. **Critic, round N+1:** resume the **same** critic with SendMessage: "Round N+1: the fixer has responded, see the thread. Verify, rule, and attack the new changes."
4. `VERDICT: PASS` ends the loop. Otherwise repeat from step 2.

Each role keeps its context: the critic remembers what it flagged, and the fixer remembers what it changed. They stay isolated from each other and from you, and the thread file is the only thing they share.

## Deadlock and the round cap

- **Deadlock:** if a finding is `upheld` twice after a dispute, the two agents disagree. Start a **fresh** `general-purpose` arbiter. Give it only that finding's block from the thread, the files it cites, and the project's rule docs (CLAUDE.md, any architecture or decision docs). It rules `critic` or `fixer` and writes `**Arbiter:** <ruling, why>` into the thread. If it rules for the fixer, it marks the finding `withdrawn`. If it rules for the critic, the fixer must fix it next round and can't dispute it again.
- **Round cap:** after 4 critic rounds without a PASS, stop and report the open findings to the user.

## At the end

Tell the user, in at most 6 lines:

- PASS or FAIL;
- the number of rounds and the Jev triage line;
- resolved, withdrawn and arbitrated counts;
- the open findings, only if it failed;
- `changed_files`;
- the thread path.

Pass on the fixer's `LESSON:` lines too. If the project keeps a learnings or decisions doc, offer to add them there. Don't commit unless the user asks.
