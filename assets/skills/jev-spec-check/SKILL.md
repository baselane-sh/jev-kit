---
name: jev-spec-check
description: Check that every rule in the project's spec docs (access rules, business rules, requirements) has a test, with Jev as the judge, then write the missing tests. Use when the user says "are our rules tested?", "check spec coverage", "check permissions coverage", "/jev-spec-check", or after changing behavior a spec describes.
---

# Jev spec check

The spec files listed in `.claude/jev-spec.json` are the human-written source of truth. Each list item and table row in them is one rule. The goal is for every rule to have a test.

1. Run `python3 .claude/skills/jev-spec-check/check.py`. Add `--spec <file>` to check one doc, or `--section <heading>` to check one area. If it says no specs are configured or a spec file isn't found, ask the user which docs hold their rules and add them to `.claude/jev-spec.json` first.
2. Show the user the summary: how many rules there are, how many have a test, and the MISSING list.
3. For each missing rule, write the test in the style of the nearest existing test file for that area. Match its framework, fixtures and assertions.
4. Run the new tests with the project's test command, then run the check again. The count should go up.

Jev only says whether a test **exists** for a rule. Running the tests is what proves the rule holds.
