#!/usr/bin/env bash
#
# One-time setup: fill in placeholders, initialise git, push to GitHub.
#
#   ./setup-github.sh <your-github-username>
#
# Safe to re-read before running. It stops on the first error and shows you
# what it's about to push before pushing it.

set -euo pipefail

USERNAME="${1:-}"
REPO="it-onboarding-automation"

if [ -z "$USERNAME" ]; then
  echo "Usage: ./setup-github.sh <your-github-username>"
  exit 1
fi

cd "$(dirname "$0")"

# --- 1. Replace the placeholder GitHub username in the docs ----------------
echo "==> Filling in GitHub username: $USERNAME"
if [[ "$OSTYPE" == "darwin"* ]]; then
  SED=(sed -i '')
else
  SED=(sed -i)
fi
"${SED[@]}" "s|github.com/<you>/|github.com/$USERNAME/|g" README.md
"${SED[@]}" "s|github.com/mjyee/|github.com/$USERNAME/|g" README.md docs/flows/leaver.md

echo "==> Remaining GitHub links (check these point somewhere real):"
grep -rn "github.com" --include="*.md" . | sed 's/^/    /'

# --- 2. Initialise the repo ------------------------------------------------
if [ ! -d .git ]; then
  echo "==> git init"
  git init -b main
fi

git add -A

# --- 3. Prove no secrets are staged ---------------------------------------
echo "==> Checking nothing sensitive is staged"
if git diff --cached --name-only | grep -E '(^|/)\.env$|\.pem$|\.key$|^audit-log/'; then
  echo "REFUSED: a secret or audit log is staged. Fix .gitignore before pushing."
  exit 2
fi
echo "    clean"

echo "==> Files to be committed:"
git diff --cached --name-only | sed 's/^/    /'

# --- 4. Commit -------------------------------------------------------------
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  git commit -m "Add leaver flow, role-access matrix, and verifying offboard tool" || true
else
  git commit -m "Initial commit: JML process design + verifying offboarding tool

- docs/role-access-matrix.md with contractor column and 90-day expiry
- docs/flows/leaver.md with Mermaid diagram
- docs/decision-log.md, six tradeoffs
- src/offboard.py: deprovision sequence with independent verification
- src/safety.py: dry-run default, admin refusal, typed confirm, audit log
- Demo mode runs the full path with zero credentials"
fi

# --- 5. Push ---------------------------------------------------------------
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "==> Adding remote"
  git remote add origin "https://github.com/$USERNAME/$REPO.git"
fi

echo "==> Pushing to https://github.com/$USERNAME/$REPO"
# If the GitHub repo was created with a README or licence, reconcile first.
git fetch origin main 2>/dev/null && git rebase origin/main || true
git push -u origin main

echo
echo "Done. Now check on GitHub:"
echo "  1. Mermaid diagram renders on the README"
echo "  2. Actions tab shows CI passing"
echo "  3. Add description + topics, and pin the repo on your profile"
echo "     https://github.com/$USERNAME/$REPO/settings"
