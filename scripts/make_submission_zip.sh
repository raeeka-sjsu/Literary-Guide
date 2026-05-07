#!/usr/bin/env bash
# Build a clean submission zip with NO secrets, NO build artifacts, NO bloat.
#
# Usage: bash scripts/make_submission_zip.sh
# Output: ../Literary-Guide-submission.zip (next to the repo, not inside it)

set -euo pipefail

# Run from anywhere — resolve repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_NAME="$(basename "${REPO_ROOT}")"
OUT="${REPO_ROOT}/../${REPO_NAME}-submission.zip"

echo "Building clean zip from: ${REPO_ROOT}"
echo "Output: ${OUT}"

# Refuse to run if a real .env still exists somewhere unsafe
if [ -f "${REPO_ROOT}/.env" ]; then
  echo "  ✓ .env detected at repo root — will be EXCLUDED from the zip."
fi

# Delete any old zip to avoid confusion
rm -f "${OUT}"

# Build the zip using rsync to a temp dir (safer than zip's --exclude on macOS)
TMPDIR_BUILD="$(mktemp -d)"
STAGE="${TMPDIR_BUILD}/${REPO_NAME}"
mkdir -p "${STAGE}"

EXCLUDE_PATTERNS=(
  --exclude='.env'
  --exclude='.env.local'
  --exclude='*.sqlite'
  --exclude='*.sqlite-journal'
  --exclude='__pycache__'
  --exclude='*.pyc'
  --exclude='.git/'
  --exclude='.git'
  --exclude='.gitignore'           # the example replaces this; user can re-add if desired
  --exclude='.DS_Store'
  --exclude='__MACOSX'
  --exclude='node_modules/'
  --exclude='node_modules'
  --exclude='venv/'
  --exclude='venv'
  --exclude='.vscode/'
  --exclude='.idea/'
  --exclude='*.tmp'
  --exclude='Literary-Guide-submission.zip'
)

# Restore .gitignore so reviewers can see how artifacts are excluded
KEEP_GITIGNORE_CONTENT="$(cat "${REPO_ROOT}/.gitignore" 2>/dev/null || echo "")"

echo "Copying files (this skips .env, venv, node_modules, .git, etc.)..."
rsync -a "${EXCLUDE_PATTERNS[@]}" "${REPO_ROOT}/" "${STAGE}/"

# Include a clean .gitignore in the submission (so the grader sees how
# artifacts are kept out)
if [ -n "${KEEP_GITIGNORE_CONTENT}" ]; then
  printf '%s\n' "${KEEP_GITIGNORE_CONTENT}" > "${STAGE}/.gitignore"
fi

# Sanity check: explicitly verify .env is NOT in the staged tree
if [ -f "${STAGE}/.env" ]; then
  echo "  ✗ ERROR: .env was copied despite exclusion. Aborting."
  exit 1
fi

# Build the zip from the staging dir, no macOS metadata
( cd "${TMPDIR_BUILD}" && zip -rq "${OUT}" "${REPO_NAME}" -x "*.DS_Store" "__MACOSX/*" )

# Cleanup staging
rm -rf "${TMPDIR_BUILD}"

# Final verification
echo ""
echo "Zip contents (any of these would be a problem):"
unzip -l "${OUT}" | grep -E "\.env|node_modules|venv|\.git/|__MACOSX|\.sqlite" || echo "  ✓ none of {.env, node_modules, venv, .git, __MACOSX, .sqlite} in zip"

SIZE_MB="$(du -m "${OUT}" | cut -f1)"
N_FILES="$(unzip -l "${OUT}" | tail -1 | awk '{print $2}')"
echo ""
echo "Done."
echo "  ${OUT}"
echo "  ${SIZE_MB} MB · ${N_FILES} files"
