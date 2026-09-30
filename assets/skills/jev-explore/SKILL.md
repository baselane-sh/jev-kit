---
name: jev-explore
description: Find where something lives in the code fast. Jev scores the repo's source files for relevance and you open only the top few. Use when the user asks where something is handled, defined or enforced ("where are refunds approved?", "what stops a user seeing another account's data?"), or says "/jev-explore <question>".
---

# Jev explore

Find code by asking Jev which files matter, instead of reading around.

1. Pick one or two keywords from the question for a pre-filter regex, e.g. `refund|approv` for "where are refunds approved?". Skip the filter if the question is conceptual.
2. Run:
   ```sh
   python3 .claude/skills/jev-explore/jev_rank.py "<the question, in plain words>" --grep "<regex>" --top 5
   ```
3. Open **only** the files it lists, highest first. Stop as soon as you have the answer. Don't read the rest of the repo.
4. Answer with the file and line, and say how many files you opened.

If the script says Jev couldn't be reached, or none of the top 5 answer the question, fall back to normal search. Say that you did.
