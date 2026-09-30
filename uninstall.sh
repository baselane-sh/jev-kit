#!/bin/bash
# Removes everything Jev Kit's install.sh added from the current project.
# Leaves your jev-rules.json / jev-spec.json in place if you customized them
# (delete by hand if you want them gone too).
set -euo pipefail

CLAUDE_DIR="${CLAUDE_DIR:-$PWD/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
HOOKS_DIR="$CLAUDE_DIR/hooks"

say() { printf '%s\n' "$*"; }

if [ ! -f "$SETTINGS" ]; then
  say "No $SETTINGS found. Nothing to do."
  exit 0
fi

if ! command -v jq >/dev/null 2>&1; then
  say "ERROR: jq is required to safely edit settings.json."
  exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$SETTINGS.bak.$STAMP"
cp "$SETTINGS" "$BACKUP"
say "Backed up settings -> $BACKUP"

TMP="$(mktemp)"
jq '
  def owned: (.command // "") | test("jev-skill-pick\\.py|jev-rules\\.py|jev-spec-hook\\.py");
  def strip_owned: [ .[]? | select( ([.hooks[]?] | map(owned) | any) | not ) ];
  .hooks = (.hooks // {})
  | .hooks.UserPromptSubmit = ( (.hooks.UserPromptSubmit // []) | strip_owned )
  | .hooks.PreToolUse       = ( (.hooks.PreToolUse // [])       | strip_owned )
  | .hooks.PostToolUse      = ( (.hooks.PostToolUse // [])      | strip_owned )
  | .hooks |= with_entries(select((.value | type) != "array" or (.value | length) > 0))
  ' "$SETTINGS" > "$TMP"

if ! jq empty "$TMP" >/dev/null 2>&1; then
  say "ERROR: generated settings.json is invalid. Left original untouched."
  rm -f "$TMP"
  exit 1
fi
mv "$TMP" "$SETTINGS"
say "Removed jev-kit hook entries from $SETTINGS"

for f in jev.py jev-rules.py jev-skill-pick.py jev-spec-hook.py test_jev_hooks.py; do
  rm -f "$HOOKS_DIR/$f"
done
rm -rf "$CLAUDE_DIR/plugins/fast-jev-compaction"
rm -rf "$CLAUDE_DIR/skills/jev-explore" "$CLAUDE_DIR/skills/adversarial-loop" "$CLAUDE_DIR/skills/jev-browser-check" "$CLAUDE_DIR/skills/jev-spec-check"
rm -f "$CLAUDE_DIR/agents/adversarial-reviewer.md" "$CLAUDE_DIR/agents/fixer.md"

LOCAL="$CLAUDE_DIR/settings.local.json"
if [ -f "$LOCAL" ]; then
  TMP="$(mktemp)"
  if jq '
    del(.extraKnownMarketplaces["fast-jev-compaction"])
    | del(.enabledPlugins["fast-jev-compaction@fast-jev-compaction"])
    | if .extraKnownMarketplaces == {} then del(.extraKnownMarketplaces) else . end
    | if .enabledPlugins == {} then del(.enabledPlugins) else . end
    ' "$LOCAL" > "$TMP" 2>/dev/null && jq empty "$TMP" >/dev/null 2>&1; then
    cat "$TMP" > "$LOCAL"
    say "Unregistered the compaction plugin from $LOCAL"
  fi
  rm -f "$TMP"
fi

say "Removed hooks, agents, plugin and skills."
say "Left in place (delete by hand if you want them gone too):"
say "  - $CLAUDE_DIR/jev-rules.json"
say "  - $CLAUDE_DIR/jev-spec.json"
say "  - $CLAUDE_DIR/settings.local.json (holds your Jev credential)"
say ""
say "Restart Claude Code to apply."
say "To undo this uninstall: cp \"$BACKUP\" \"$SETTINGS\""
