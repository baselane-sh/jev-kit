#!/bin/bash
# ============================================================================
#  Jev Kit - installer
#
#  Drops the .claude/ pack for Jev (TypeSafe's decision model) into the
#  CURRENT project and wires it into .claude/settings.json:
#    1. hooks/jev.py               shared client every hook/skill imports
#    2. hooks/jev-skill-pick.py    UserPromptSubmit  -> picks one skill (or none)
#    3. hooks/jev-rules.py         PreToolUse        -> blocks edits that break jev-rules.json
#    4. hooks/jev-spec-hook.py     PostToolUse       -> flags spec rules with no test
#    5. skills/jev-explore         faster file search (keyword filter + Jev ranking)
#    6. skills/adversarial-loop    cheap risk triage before full code review
#    7. skills/jev-browser-check   Playwright + Jev click-picker for browser QA
#    8. plugins/fast-jev-compaction  replaces /compact with Jev decisions
#
#  Every hook fails open: no key, a timeout, or a Gateway error means the
#  hook does nothing and Claude Code carries on as normal.
#
#  Safe to re-run: it removes its own previous hook entries before re-adding,
#  and always backs up settings.json first. Nothing else in your config is
#  touched. Project-scoped: everything lands under ./.claude, not ~/.claude,
#  because jev-rules.json and jev-spec.json are meant to be per-project.
# ============================================================================
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="${CLAUDE_DIR:-$PWD/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
HOOKS_DIR="$CLAUDE_DIR/hooks"

say() { printf '%s\n' "$*"; }

if ! command -v jq >/dev/null 2>&1; then
  say "ERROR: jq is required. Install it first:"
  say "  macOS:   brew install jq"
  say "  Debian:  sudo apt-get install -y jq"
  say ""
  say "No jq? Merge assets/settings.json into .claude/settings.json by hand."
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  say "ERROR: python3 is required (every hook and skill uses it, stdlib only)."
  exit 1
fi

mkdir -p "$CLAUDE_DIR" "$HOOKS_DIR"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$SETTINGS.bak.$STAMP"
cp "$SETTINGS" "$BACKUP"
say "Backed up settings -> $BACKUP"

say "Copying hooks, skills, agents and the compaction plugin into $CLAUDE_DIR ..."
cp "$SRC_DIR/assets/hooks/jev.py"             "$HOOKS_DIR/"
cp "$SRC_DIR/assets/hooks/jev-rules.py"       "$HOOKS_DIR/"
cp "$SRC_DIR/assets/hooks/jev-skill-pick.py"  "$HOOKS_DIR/"
cp "$SRC_DIR/assets/hooks/jev-spec-hook.py"   "$HOOKS_DIR/"
cp "$SRC_DIR/assets/hooks/test_jev_hooks.py"  "$HOOKS_DIR/"
chmod +x "$HOOKS_DIR"/jev*.py

mkdir -p "$CLAUDE_DIR/agents" "$CLAUDE_DIR/skills" "$CLAUDE_DIR/plugins"
cp -r "$SRC_DIR/assets/agents/." "$CLAUDE_DIR/agents/"
cp -r "$SRC_DIR/assets/skills/." "$CLAUDE_DIR/skills/"
cp -r "$SRC_DIR/assets/plugins/." "$CLAUDE_DIR/plugins/"

if [ ! -f "$CLAUDE_DIR/jev-rules.json" ]; then
  cp "$SRC_DIR/assets/jev-rules.json" "$CLAUDE_DIR/jev-rules.json"
  say "Wrote $CLAUDE_DIR/jev-rules.json (4 generic examples - edit these for your project)"
else
  say "Kept existing $CLAUDE_DIR/jev-rules.json untouched"
fi
if [ ! -f "$CLAUDE_DIR/jev-spec.json" ]; then
  cp "$SRC_DIR/assets/jev-spec.json" "$CLAUDE_DIR/jev-spec.json"
  say "Wrote $CLAUDE_DIR/jev-spec.json (edit the spec/watch paths for your project)"
else
  say "Kept existing $CLAUDE_DIR/jev-spec.json untouched"
fi

say "Installed hooks -> $HOOKS_DIR/"

TMP="$(mktemp)"
jq \
  --arg pick  "python3 \"\$CLAUDE_PROJECT_DIR/.claude/hooks/jev-skill-pick.py\"" \
  --arg rules "python3 \"\$CLAUDE_PROJECT_DIR/.claude/hooks/jev-rules.py\"" \
  --arg spec  "python3 \"\$CLAUDE_PROJECT_DIR/.claude/hooks/jev-spec-hook.py\"" \
  '
  def owned: (.command // "") | test("jev-skill-pick\\.py|jev-rules\\.py|jev-spec-hook\\.py");
  def strip_owned: [ .[]? | select( ([.hooks[]?] | map(owned) | any) | not ) ];

  .hooks = (.hooks // {})
  | .hooks.UserPromptSubmit = ( (.hooks.UserPromptSubmit // []) | strip_owned ) + [
      { "matcher": "*",
        "hooks": [ { "type": "command", "command": $pick, "timeout": 10, "statusMessage": "jev-skill-pick" } ] }
    ]
  | .hooks.PreToolUse = ( (.hooks.PreToolUse // []) | strip_owned ) + [
      { "matcher": "Write|Edit|MultiEdit|Bash",
        "hooks": [ { "type": "command", "command": $rules, "timeout": 10, "statusMessage": "jev-rules" } ] }
    ]
  | .hooks.PostToolUse = ( (.hooks.PostToolUse // []) | strip_owned ) + [
      { "matcher": "Write|Edit|MultiEdit",
        "hooks": [ { "type": "command", "command": $spec, "timeout": 30, "statusMessage": "jev-spec-check" } ] }
    ]
  ' "$SETTINGS" > "$TMP"

if ! jq empty "$TMP" >/dev/null 2>&1; then
  say "ERROR: generated settings.json is invalid. Left original untouched."
  say "Backup is at $BACKUP"
  rm -f "$TMP"
  exit 1
fi
mv "$TMP" "$SETTINGS"

LOCAL="$CLAUDE_DIR/settings.local.json"
PLUGIN_ABS="$CLAUDE_DIR/plugins/fast-jev-compaction"
if [ ! -f "$LOCAL" ]; then
  echo '{}' > "$LOCAL"
fi
python3 - "$LOCAL" "$PLUGIN_ABS" << 'PYEOF'
import json, sys
local_path, plugin_path = sys.argv[1], sys.argv[2]
with open(local_path) as f:
    data = json.load(f)
env = data.setdefault("env", {})
if "CLAUDE_CODE_ENABLE_FUNCTION_HOOKS" not in env:
    env["CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"] = "1"
markets = data.setdefault("extraKnownMarketplaces", {})
markets["fast-jev-compaction"] = {"source": {"source": "directory", "path": plugin_path}}
enabled = data.setdefault("enabledPlugins", {})
enabled["fast-jev-compaction@fast-jev-compaction"] = True
with open(local_path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
say "Registered the compaction plugin in $LOCAL"

GITIGNORE="$PWD/.gitignore"
touch "$GITIGNORE"
for line in ".claude/settings.local.json" ".claude/.playwright/"; do
  grep -qxF "$line" "$GITIGNORE" || echo "$line" >> "$GITIGNORE"
done

say ""
if [ -z "${AI_GATEWAY_API_KEY:-}" ] && [ -t 0 ]; then
  say "Jev runs through Vercel AI Gateway."
  say "Create a credential at: https://vercel.com/dashboard -> your project -> AI Gateway -> API Keys"
  printf "Paste it now (or press Enter to skip): "
  read -r USER_CRED || USER_CRED=""
else
  USER_CRED="${AI_GATEWAY_API_KEY:-}"
fi

if [ -n "${USER_CRED:-}" ]; then
  python3 - "$LOCAL" "$USER_CRED" << 'PYEOF'
import json, sys
local_path, cred = sys.argv[1], sys.argv[2]
with open(local_path) as f:
    data = json.load(f)
env = data.setdefault("env", {})
env["AI_GATEWAY_API_KEY"] = cred
env["TYPESAFE_API_KEY"] = cred
env.setdefault("TYPESAFE_BASE_URL", "https://ai-gateway.vercel.sh/typesafe")
with open(local_path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
  chmod 600 "$LOCAL"
  say "Saved the credential into $LOCAL (chmod 600, gitignored)."
else
  say "No credential provided. Every hook fails open, so Claude Code keeps working -"
  say "Jev just won't be called until AI_GATEWAY_API_KEY is set in .claude/settings.local.json."
fi

say ""
say "Done. Installed:"
say "  - jev-skill-pick  (UserPromptSubmit) - picks one skill for your prompt, or none"
say "  - jev-rules       (PreToolUse)       - blocks edits that break a rule in jev-rules.json"
say "  - jev-spec-check  (PostToolUse)      - flags spec rules with no test"
say "  - skills/jev-explore, skills/adversarial-loop, skills/jev-browser-check"
say "  - plugins/fast-jev-compaction        - registered, run /compact to use it"
say ""
say "Next steps:"
say "  1. Edit .claude/jev-rules.json and .claude/jev-spec.json for this project"
say "  2. Restart Claude Code (or start a new session) to load the changes"
say "  3. Check the wiring (offline): python3 $HOOKS_DIR/test_jev_hooks.py"
say "  4. To undo everything: bash $SRC_DIR/uninstall.sh"
say ""
say "To restore the previous settings.json: cp \"$BACKUP\" \"$SETTINGS\""
