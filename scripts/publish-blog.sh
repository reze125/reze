#!/usr/bin/env bash
set -euo pipefail

BLOG_DIR="${1:?Usage: publish-blog.sh <blog-dir> [commit-message]}"
MSG="${2:-Auto-publish by REZE $(date +%Y-%m-%d)}"
BLOG_PATH="$HOME/$BLOG_DIR"

if [ ! -d "$BLOG_PATH/.git" ]; then
    echo "ERROR: Not a git repo: $BLOG_PATH"
    exit 1
fi

cd "$BLOG_PATH"
git add -A
if git diff --cached --quiet; then
    echo "Nothing to commit"
    exit 0
fi
git commit -m "$MSG"
git push
echo "OK: Pushed to $BLOG_DIR"
