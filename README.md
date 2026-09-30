# jev-kit

One-shot installer for a set of Claude Code hooks, skills and agents built on
TypeSafe's Jev decision model, served through Vercel AI Gateway. Drop it into
any project's `.claude/` folder.

## What it installs

- **`hooks/jev.py`** — shared client every hook and skill imports
- **`hooks/jev-skill-pick.py`** (UserPromptSubmit) — reads your project's
  skills and picks the one that fits the prompt, or none
- **`hooks/jev-rules.py`** (PreToolUse) — blocks edits and commits that break
  a hard rule in `jev-rules.json`
- **`hooks/jev-spec-hook.py`** (PostToolUse) — flags spec rules with no test
  coverage after an edit
- **`skills/jev-explore`** — faster file search (keyword filter + ranking)
- **`skills/adversarial-loop`** — cheap risk triage before a full code review,
  backed by `agents/adversarial-reviewer.md` and `agents/fixer.md`
- **`skills/jev-spec-check`** — judges which spec rules have tests (used by
  the spec hook, or run on demand with `/jev-spec-check`)
- **`skills/jev-browser-check`** — Playwright + Jev click-picker for browser QA
- **`plugins/fast-jev-compaction`** — replaces `/compact` with Jev-guided
  compaction

Every hook fails open: no API key, a timeout, or a Gateway error means the
hook does nothing and Claude Code carries on as normal. Nothing here can block
you from working.

## Install

```bash
git clone https://github.com/baselane-sh/jev-kit.git /tmp/jev-kit
cd /path/to/your/project
bash /tmp/jev-kit/install.sh
```

It will:
1. Back up your current `.claude/settings.json`
2. Copy the hooks, skills, agents and compaction plugin into `.claude/`
3. Merge the hook wiring into `.claude/settings.json` (idempotent — safe to
   re-run, it replaces its own entries instead of duplicating them)
4. Register the compaction plugin in `.claude/settings.local.json`
5. Prompt for a Vercel AI Gateway API key, save it locally
   (`chmod 600`, gitignored) — or skip, since every hook fails open anyway
6. Add `.claude/settings.local.json` and `.claude/.playwright/` to
   `.gitignore`

Requires `jq` and `python3` (stdlib only). Restart Claude Code (or start a new
session) after installing, then check the wiring offline (no key or network
needed):
```bash
python3 .claude/hooks/test_jev_hooks.py
```

## Uninstall

```bash
bash /tmp/jev-kit/uninstall.sh
```

Removes only what the installer added: the hook entries in
`settings.json`, the hook scripts, the skills, the agents, and the compaction
plugin and its registration in `settings.local.json`. Leaves your customized
`jev-rules.json`, `jev-spec.json` and the rest of `settings.local.json`
(including your key) in place — delete those by hand if you want them gone
too.

## Configure

- `.claude/jev-rules.json` — hard rules to check before every edit/commit.
  Move "never do X" out of your `CLAUDE.md` and into here.
- `.claude/jev-spec.json` — points at spec docs and the code paths they cover,
  so the spec hook knows what to check for test coverage.

Env vars (set in `.claude/settings.local.json` → `env`):
`AI_GATEWAY_API_KEY` (hooks and skills) and `TYPESAFE_API_KEY` /
`TYPESAFE_BASE_URL` (compaction plugin) — the installer sets all three.

Tuning: `JEV_URL`, `JEV_TIMEOUT` (3s), `JEV_LOG`, `JEV_SKILL_THRESHOLD` (0.6),
`JEV_RULES_BLOCK` / `JEV_RULES_WARN` (0.8 / 0.5), `JEV_TRIAGE_LOW` (0.2),
`JEV_EXPLORE_EXT`, `JEV_BASE_URL` / `JEV_LOGIN_PATH`, `JEV_PARALLEL` (4),
`JEV_RETRIES` (0), `JEV_MODEL` (`typesafe-ai/jev`).

## License

MIT.
