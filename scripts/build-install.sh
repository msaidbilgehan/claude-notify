#!/usr/bin/env bash
#
# build-install.sh - Build claude-notify and (re)install its CLI with uv.
#
# Rebuilds the package and installs the `claude-notify` command as a uv tool, so
# the latest source is what runs on your PATH. Quality gates (ruff, mypy,
# pytest) run first by default; nothing is installed if they fail.
#
# Usage:
#   scripts/build-install.sh [OPTIONS]
#
# Options:
#   -e, --editable     Install editable (default): the CLI imports straight from
#                      this source tree, so later edits are live with no rebuild.
#   -w, --wheel        Build a wheel and install that pinned artifact instead
#                      (non-editable; re-run after each change to update).
#       --skip-checks  Skip the ruff/mypy/pytest gate (alias: --skip-tests).
#   -h, --help         Show this help and exit.
#
# Dependencies:
#   - uv   https://docs.astral.sh/uv/
#
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
readonly SCRIPT_DIR REPO_ROOT SCRIPT_NAME

# --- logging ---------------------------------------------------------------

# Print a timestamped, levelled message to stderr (data goes to stdout only).
log() {
  local level="${1}"
  shift
  printf '[%s] [%-5s] %s\n' "$(date '+%H:%M:%S')" "${level}" "$*" >&2
}

die() {
  log "ERROR" "$*"
  exit 1
}

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} [OPTIONS]

Build claude-notify and (re)install the 'claude-notify' CLI as a uv tool.
Quality gates (ruff, mypy, pytest) run first unless skipped; nothing is
installed if they fail.

Options:
  -e, --editable     Install editable (default): the CLI imports from this
                     source tree, so later edits are live with no rebuild.
  -w, --wheel        Build a wheel and install that pinned artifact instead
                     (non-editable; re-run after each change to update).
      --skip-checks  Skip the ruff/mypy/pytest gate (alias: --skip-tests).
  -h, --help         Show this help and exit.

Examples:
  ${SCRIPT_NAME}                  # quality gates, then editable install
  ${SCRIPT_NAME} --wheel          # quality gates, then build + install a wheel
  ${SCRIPT_NAME} -e --skip-checks # fast editable reinstall, no gates
EOF
}

# --- steps -----------------------------------------------------------------

# Run linage, typing, and tests through the project's uv environment.
# Returns non-zero if any gate fails (callers decide whether to abort).
run_checks() {
  log "INFO" "Running quality gates (ruff, mypy, pytest)..."
  uv run ruff check . || return 1
  uv run mypy claude_notify || return 1
  uv run pytest -q || return 1
}

install_editable() {
  log "INFO" "Installing editable uv tool (live source tree)..."
  uv tool install --editable "${REPO_ROOT}" --force
}

install_wheel() {
  log "INFO" "Building wheel with 'uv build'..."
  rm -rf "${REPO_ROOT}/dist"
  uv build --wheel

  local wheels=()
  shopt -s nullglob
  wheels=("${REPO_ROOT}"/dist/*.whl)
  shopt -u nullglob

  # dist/ was just cleared, so a normal build leaves exactly one wheel. Index 0
  # (not a negative subscript — those need Bash 4.3+, but macOS ships 3.2).
  (( ${#wheels[@]} > 0 )) || die "uv build produced no wheel in dist/"
  (( ${#wheels[@]} == 1 )) || log "WARN" "Multiple wheels in dist/; installing the first."

  local wheel="${wheels[0]}"
  log "INFO" "Installing ${wheel##*/}..."
  uv tool install "${wheel}" --force
}

verify_install() {
  # Refresh the shell's command lookup in case the tool bin was just linked.
  hash -r 2>/dev/null || true
  if command -v claude-notify >/dev/null 2>&1; then
    log "INFO" "Done — $(claude-notify --version)"
  else
    log "WARN" "Installed, but 'claude-notify' is not on PATH."
    log "WARN" "Add uv's tool bin to PATH:  uv tool update-shell  (then restart your shell)"
  fi
}

# --- main ------------------------------------------------------------------

main() {
  local mode="editable"
  local run_gates=true

  while [[ $# -gt 0 ]]; do
    case "${1}" in
      -e|--editable)              mode="editable"; shift ;;
      -w|--wheel)                 mode="wheel"; shift ;;
      --skip-checks|--skip-tests) run_gates=false; shift ;;
      -h|--help)                  usage; exit 0 ;;
      --)                         shift; break ;;
      -*)                         usage >&2; die "Unknown option: ${1}" ;;
      *)                          usage >&2; die "Unexpected argument: ${1}" ;;
    esac
  done

  command -v uv >/dev/null 2>&1 \
    || die "uv not found. Install it from https://docs.astral.sh/uv/"

  cd "${REPO_ROOT}" || die "Cannot enter repo root: ${REPO_ROOT}"
  [[ -f pyproject.toml ]] || die "pyproject.toml not found in ${REPO_ROOT}"
  grep -q 'name = "claude-notify"' pyproject.toml \
    || die "${REPO_ROOT} does not look like the claude-notify project"

  if [[ "${run_gates}" == true ]]; then
    run_checks \
      || die "Quality gates failed — not installing. Fix the issues above, or re-run with --skip-checks."
  else
    log "WARN" "Skipping quality gates (--skip-checks)."
  fi

  case "${mode}" in
    editable) install_editable ;;
    wheel)    install_wheel ;;
  esac

  verify_install
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
