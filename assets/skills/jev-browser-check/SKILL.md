---
name: jev-browser-check
description: Click through the running app with a browser agent where Jev picks every click, to check that a flow works or that each role can only reach what the spec allows. Use when the user says "check it in the browser", "check the roles in the browser", "/jev-browser-check", or wants to see what a user or role can reach.
---

# Jev browser check

The app needs to be running. Find the dev command and port from `package.json`, the README or CLAUDE.md, and pass the URL with `--base` (the default is `http://localhost:3000`).

1. Pick the goals.
   - **Flow check:** one plain-words goal per flow, e.g. "add an item to the cart and reach checkout".
   - **Role check:** read the project's access spec (`.claude/jev-spec.json` lists it, often `docs/PERMISSIONS.md`) and pick goals that one role should be refused and another allowed, e.g. `viewer` and `admin` both try "open the admin settings page".
2. For roles, the agent needs a way to sign in. Use a saved Playwright session at `.playwright/auth-<role>.json`, or set `JEV_<ROLE>_USER` / `JEV_<ROLE>_PASSWORD` and it signs in through `--login-path` (default `/login`) and saves the session. If neither exists, ask the user for test accounts. Never use real users' credentials.
3. For each goal, run:
   ```sh
   uv run --with playwright python .claude/skills/jev-browser-check/agent.py --goal "<goal>" [--role <role>] [--base <url>] [--start /path]
   ```
   Add `--headed` to watch it, or `--skip "<regex>"` to hide elements it should never press (for example a demo "view as" role switcher). On the first run, you may need `uv run --with playwright playwright install chromium`.
4. `outcome` is `done`, `blocked`, `gave up` or `jev unreachable`, and `p_not_allowed` is Jev's read of the final page. You make the final call. Compare each run with what the spec or task says, and report a table: role, goal, expected, got.

The agent never presses buttons that change data (approve, save, delete…) unless you pass `--allow-writes`. Only use that flag against a throwaway or demo database.
