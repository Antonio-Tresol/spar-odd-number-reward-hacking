#!/usr/bin/env bash
# Install the harness's git hooks into this repository.
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"
hook_dir="$repo_root/.git/hooks"
mkdir -p "$hook_dir"
install -m 755 "$repo_root/hooks/pre-commit" "$hook_dir/pre-commit"
echo "Installed pre-commit hook into $hook_dir"
echo "Bypass a single commit with: git commit --no-verify"
