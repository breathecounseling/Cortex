#!/bin/bash
set -e

HOOKS_DIR=".git/hooks"
HOOK_FILE="$HOOKS_DIR/pre-push"

mkdir -p "$HOOKS_DIR"

cat > "$HOOK_FILE" <<'EOF'
#!/bin/sh
echo "🔍 Running tests before push..."
pytest -q --maxfail=1 --disable-warnings
RESULT=$?
if [ $RESULT -ne 0 ]; then
  echo "❌ Tests failed. Push aborted."
  exit 1
fi
echo "✅ Tests passed. Proceeding with push."
exit 0
EOF

chmod +x "$HOOK_FILE"

echo "✅ Pre-push hook installed. It will run pytest before every git push."