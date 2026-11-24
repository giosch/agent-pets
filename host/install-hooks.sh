#!/bin/bash
# install-hooks.sh — Installs Agent Pets notification hooks into Claude Code settings.
# Usage: ./install-hooks.sh

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAWD_NOTIFY="$SCRIPT_DIR/agent-pets-notify"
SETTINGS_FILE="${SETTINGS_FILE:-$HOME/.claude/settings.json}"

if [ ! -f "$CLAWD_NOTIFY" ]; then
    echo "Error: agent-pets-notify not found at $CLAWD_NOTIFY"
    exit 1
fi

if ! command -v jq &>/dev/null; then
    echo "Error: jq is required but not installed. Install with: brew install jq"
    exit 1
fi

# Build the hooks JSON
HOOKS_JSON=$(cat <<ENDJSON
{
  "Notification": [
    {
      "matcher": "idle_prompt",
      "hooks": [
        {
          "type": "command",
          "command": "$CLAWD_NOTIFY"
        }
      ]
    }
  ],
  "UserPromptSubmit": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "$CLAWD_NOTIFY"
        }
      ]
    }
  ],
  "SessionEnd": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "$CLAWD_NOTIFY"
        }
      ]
    }
  ]
}
ENDJSON
)

# Create settings file if it doesn't exist
if [ ! -f "$SETTINGS_FILE" ]; then
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    echo '{}' > "$SETTINGS_FILE"
fi

# Merge hooks into existing settings (preserves all other keys)
UPDATED=$(jq --argjson hooks "$HOOKS_JSON" '.hooks = (.hooks // {}) * $hooks' "$SETTINGS_FILE")
echo "$UPDATED" > "$SETTINGS_FILE"

echo "Agent Pets hooks installed into $SETTINGS_FILE"
echo "Hook command: $CLAWD_NOTIFY"
echo ""
echo "NOTE: The 'matcher' field filters which notification types trigger the hook."
echo "If your Claude Code version doesn't support 'matcher', remove it —"
echo "agent-pets-notify already filters by notification_type in protocol.py."
