#!/usr/bin/env bash
#
# Order 1 wizard: source, register, review, and capture ONE evaluation wallet,
# then verify the readiness report. This is the human-review step that
# app.services.anomaly_ranking cannot do for itself: only a person can vouch
# for a wallet's independent source and choose an analysis window.
#
# Run from anywhere:  bash scripts/review_evaluation_wizard.sh
# Re-run it for each additional wallet; stages are idempotent and remember
# values already saved to api/.env.
#
# Nothing here decides a review for you, and nothing invents a source. The
# registry write and the live capture are each gated behind a dry-run plus an
# explicit confirmation.
#
# Everything above the "STAGES" marker is the wizard library: do not hand-edit
# it. Author the per-step stages below the marker.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Wizard library: delightful, consistent UX, identical across every wizard.
# ──────────────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); RED=$(tput setaf 1)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""; RED=""
fi

# Author sets this at the top of the stages section.
TOTAL_STAGES=0

_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()    # KEYs written to ENV_FILE this run
WRITTEN_SECRET=() # secret NAMEs set this run
SKIPPED=()        # things we couldn't do (e.g. gh missing)

# _clear wipes the terminal so only the current step is on screen. No-op when
# output isn't a terminal, so piped logs stay readable.
_clear() {
  [[ -t 1 ]] || return 0
  if command -v tput >/dev/null 2>&1; then tput clear; else printf '\033[2J\033[3J\033[H'; fi
}

# banner "Title" shows the opening frame: what this wizard does.
banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages%s\n\n' "$DIM" "$TOTAL_STAGES" "$RESET"
  printf '%s  You drive the browser; this wizard tells you exactly what to do and\n' "$DIM"
  printf '  captures the values you copy back. Stop any time with Ctrl-C and re-run\n'
  printf '  later, since it remembers values already saved.%s\n' "$RESET"
  pause "Ready to start?"
}

# stage "Name" clears the screen, then announces a stage and shows progress.
# Clearing keeps only the current step on screen.
stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  printf '\n%s%s▸ Stage %s/%s · %s%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET"
}

# say "..." prints a plain instruction line.
say()  { printf '  %s\n' "$1"; }
# step "..." is a numbered-feeling action the human takes in the browser.
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }

# open_url URL opens it in the human's browser, cross-platform incl. WSL.
open_url() {
  local url="$1"
  printf '  %s↗ opening%s %s\n' "$GREEN" "$RESET" "$url"
  { if   command -v wslview     >/dev/null 2>&1; then wslview "$url"
    elif command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$url"
    elif command -v xdg-open    >/dev/null 2>&1; then xdg-open "$url"
    elif command -v open        >/dev/null 2>&1; then open "$url"
    else warn "couldn't open a browser; visit it manually: $url"; fi
  } >/dev/null 2>&1 || warn "couldn't open a browser, so visit it manually: $url"
}

# pause "msg" waits for the human to confirm they've done the manual part.
pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ || true
}

# confirm "question" is a y/N gate; returns success on yes.
confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  read -r reply || true
  [[ "$reply" =~ ^[Yy] ]]
}

# _existing KEY: current value of KEY in ENV_FILE, if any.
_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  printf '%s' "${line#*=}"
}

# ask KEY "Prompt" reads a value into $KEY. Offers the existing .env value as
# a default on re-runs (Enter keeps it). Visible input (non-secret).
ask() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -r input || true
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# ask_secret KEY "Prompt" is like ask, but input is hidden.
ask_secret() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -rs input || true
  printf '\n'
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# write_env KEY VALUE upserts KEY=VALUE into ENV_FILE (creates it; replaces
# any existing line). Idempotent.
write_env() {
  local key="$1" value="$2" tmp
  touch "$ENV_FILE"
  tmp=$(mktemp)
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  WRITTEN_ENV+=("$key")
  printf '  %s✓ wrote%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}

# set_secret NAME VALUE sets a GitHub Actions repo secret via gh. Falls back
# to a warning (and records it) if gh is unavailable or unauthenticated.
set_secret() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if printf '%s' "$value" | gh secret set "$name" >/dev/null 2>&1; then
      WRITTEN_SECRET+=("$name")
      printf '  %s✓ set%s GitHub secret %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub secret $name (set it manually: gh secret set $name)")
  warn "skipped GitHub secret $name: gh not ready; set it later"
}

# set_var NAME VALUE sets a GitHub Actions repo variable (non-secret).
set_var() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh variable set "$name" --body "$value" >/dev/null 2>&1; then
      printf '  %s✓ set%s GitHub variable %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub variable $name")
  warn "skipped GitHub variable $name, gh not ready; set it later"
}

# finish clears, then shows a closing summary of everything configured.
finish() {
  _clear
  printf '\n%s%s  ✓ Setup complete%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} ))    && note "wrote ${#WRITTEN_ENV[@]} value(s) to $ENV_FILE: ${WRITTEN_ENV[*]}"
  (( ${#WRITTEN_SECRET[@]} )) && note "set ${#WRITTEN_SECRET[@]} GitHub secret(s): ${WRITTEN_SECRET[*]}"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "still to do by hand:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}

# ──────────────────────────────────────────────────────────────────────────
# STAGES: author this section. One stage() per step the human takes.
# Replace the example below. Set TOTAL_STAGES to match the stages you write.
# ──────────────────────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO_ROOT/api"
DATA_DIR="${EVAL_DATA_DIR:-$REPO_ROOT/data}"
REGISTRY="${EVAL_REGISTRY:-$DATA_DIR/evaluation_wallets.csv}"
COLLECT_OUT="${EVAL_COLLECT_OUT:-$REPO_ROOT/var/collect-behavioral-evidence}"
EVIDENCE_ROOT="${EVAL_EVIDENCE_ROOT:-$COLLECT_OUT/by-wallet}"
DATASET_OUT="${EVAL_DATASET_OUT:-$REPO_ROOT/var/evaluation-dataset}"
READINESS_OUT="${EVAL_READINESS_OUT:-$REPO_ROOT/var/evaluation-readiness/readiness.json}"
USDT_TRC20_CONTRACT="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
ENV_FILE="${WIZARD_ENV_FILE:-$API_DIR/.env}"
if [[ -n "${WIZARD_RUNNER:-}" ]]; then
  read -r -a RUN <<< "$WIZARD_RUNNER"
else
  RUN=(uv run --project "$API_DIR" python)
fi

TOTAL_STAGES=5

banner "Order 1: review an evaluation wallet and capture a saved window"

# ── Stage 1: the live-capture key ─────────────────────────────────────────
stage "TronGrid API key"
say "The capture in stage 4 reads TRON through TronGrid. The key is sent as the"
say "TRON-PRO-API-KEY header: it grants read access only, signs nothing, and moves"
say "nothing. Without it, live capture stays disabled rather than running bare."
open_url "https://www.trongrid.io/"
step "Sign in, open your dashboard / API keys section, and create an API key."
step "Copy the key value."
ask_secret CFA_TRON_API_KEY "Paste the TronGrid API key:"
write_env CFA_TRON_API_KEY "$CFA_TRON_API_KEY"
note "Leaving CFA_DATA_MODE as-is; the evaluation-wallet capture does not need LIVE mode."
pause "Saved to api/.env. Press Enter for stage 2."

# ── Stage 2: identify the wallet, then register it only if it is new ──────
stage "Identify the evaluation wallet"
say "An evaluation wallet needs an INDEPENDENT source. If this exact record"
say "already exists here and is already accepted, the wizard resumes at capture"
say "and skips registration and review; otherwise it walks you through both."
ask EVAL_ADDRESS "Wallet address (TRON, 34 chars):"
ask EVAL_CATEGORY "Control category (self_custody | frequent_exchange_customer | payment_service | energy_rental_recipient | other_operational_confounder):"

# Resume check. Exit codes are explicit (see scripts/evaluation_wallet_resume.py);
# handled here rather than allowed to trip `set -e`, so an expected status can
# branch instead of aborting the run.
RESUME_ACCEPTED=0
RESUME_RC=0
"${RUN[@]}" "$REPO_ROOT/scripts/evaluation_wallet_resume.py" \
  --network tron --address "$EVAL_ADDRESS" --category "$EVAL_CATEGORY" \
  --registry "$REGISTRY" || RESUME_RC=$?
case "$RESUME_RC" in
  0)
    RESUME_ACCEPTED=1
    note "existing registry record found for $EVAL_ADDRESS"
    note "Stage 2 (register) skipped: the record already exists"
    note "existing accepted review found"
    note "Stage 3 (review) skipped: the review is already accepted"
    ;;
  10)
    note "no existing record; continuing with registration and review"
    ;;
  11)
    warn "existing record for $EVAL_ADDRESS is present but NOT accepted"
    note "Stage 2 (register) skipped: a duplicate cannot be appended"
    note "Stage 3 (review) still required: a human must decide this record"
    ;;
  12|13|14)
    warn "resume refused (exit $RESUME_RC); see the message above"
    warn "stopping without touching any registry or review file"
    exit "$RESUME_RC"
    ;;
  *)
    warn "unexpected resume-check exit code $RESUME_RC; stopping"
    exit 1
    ;;
esac

if [[ "$RESUME_RC" -eq 10 ]]; then
  say "Register the wallet: you supply the source, and you are named as the reviewer."
  ask EVAL_SOURCE_REFERENCE "Source reference (URL or citation):"
  if [[ -n "${EVAL_SOURCE_REFERENCE:-}" ]]; then open_url "$EVAL_SOURCE_REFERENCE"; fi
  step "Check the source actually says what you are about to claim."
  ask EVAL_EVIDENCE_TYPE "Evidence type (one line: what the source establishes):"
  ask EVAL_REVIEWER "Your reviewer identity (name or email):"
  ask EVAL_DATA_MODE "Data mode (RECORDED_PUBLIC | SYNTHETIC) [RECORDED_PUBLIC]:"
  [[ -z "${EVAL_DATA_MODE:-}" ]] && EVAL_DATA_MODE="RECORDED_PUBLIC"
  note "Dry run first -- nothing is written yet:"
  "${RUN[@]}" "$REPO_ROOT/scripts/ingest_evaluation_wallet.py" \
    --network tron --address "$EVAL_ADDRESS" --category "$EVAL_CATEGORY" \
    --source-reference "$EVAL_SOURCE_REFERENCE" --evidence-type "$EVAL_EVIDENCE_TYPE" \
    --reviewer "$EVAL_REVIEWER" --data-mode "$EVAL_DATA_MODE" --path "$REGISTRY"
  if confirm "Append this record to $REGISTRY?"; then
    "${RUN[@]}" "$REPO_ROOT/scripts/ingest_evaluation_wallet.py" \
      --network tron --address "$EVAL_ADDRESS" --category "$EVAL_CATEGORY" \
      --source-reference "$EVAL_SOURCE_REFERENCE" --evidence-type "$EVAL_EVIDENCE_TYPE" \
      --reviewer "$EVAL_REVIEWER" --data-mode "$EVAL_DATA_MODE" --path "$REGISTRY" --write
  else
    warn "registration skipped; stopping so stage 3 has nothing stale to review"
    exit 0
  fi
fi

# ── Stage 3: review the record ────────────────────────────────────────────
stage "Review the wallet"
if [[ "$RESUME_ACCEPTED" -eq 1 ]]; then
  note "existing accepted review found for $EVAL_ADDRESS; Stage 3 skipped"
else
  say "First print the review packet. This shows what is on file; it decides nothing."
  "${RUN[@]}" "$REPO_ROOT/scripts/review_evaluation_wallet.py" \
    --network tron --address "$EVAL_ADDRESS" --category "$EVAL_CATEGORY" \
    --data-dir "$DATA_DIR" --evidence-root "$EVIDENCE_ROOT"
  if [[ -z "${EVAL_REVIEWER:-}" ]]; then ask EVAL_REVIEWER "Your reviewer identity (name or email):"; fi
  ask EVAL_RATIONALE "Rationale (why this source is independent and adequate):"
  ask EVAL_EVIDENCE_INSPECTED "Evidence inspected (the source_reference or upstream id):"
  note "Dry run first -- the registry and its audit log are untouched:"
  "${RUN[@]}" "$REPO_ROOT/scripts/review_evaluation_wallet.py" \
    --network tron --address "$EVAL_ADDRESS" --category "$EVAL_CATEGORY" \
    --action accept --reviewer "$EVAL_REVIEWER" \
    --rationale "$EVAL_RATIONALE" --evidence-inspected "$EVAL_EVIDENCE_INSPECTED" \
    --data-dir "$DATA_DIR" --evidence-root "$EVIDENCE_ROOT"
  if confirm "Apply this decision (writes evaluation_wallets.csv and evaluation_review_log.csv)?"; then
    "${RUN[@]}" "$REPO_ROOT/scripts/review_evaluation_wallet.py" \
      --network tron --address "$EVAL_ADDRESS" --category "$EVAL_CATEGORY" \
      --action accept --reviewer "$EVAL_REVIEWER" \
      --rationale "$EVAL_RATIONALE" --evidence-inspected "$EVAL_EVIDENCE_INSPECTED" \
      --data-dir "$DATA_DIR" --evidence-root "$EVIDENCE_ROOT" --write
  else
    warn "decision not applied"
  fi
fi

# ── Stage 4: capture one saved window (network) ───────────────────────────
stage "Capture a saved behavioral window (network)"
say "This calls TronGrid and saves one bundle under"
say "$EVIDENCE_ROOT/tron/<address>/<run_id>/. Each capture gets its own run id,"
say "so distinct windows coexist and no earlier bundle is overwritten. In"
say "evaluation-wallet mode it never writes behavioral_evidence.csv and cannot"
say "promote the wallet."
ask TOKEN_CONTRACT "Token contract [Enter for USDT-TRC20]:"
[[ -z "${TOKEN_CONTRACT:-}" ]] && TOKEN_CONTRACT="$USDT_TRC20_CONTRACT"
ask WINDOW_START "Scan start (UTC ISO8601, e.g. 2026-08-01T00:00:00Z):"
ask WINDOW_CUTOFF "Scan cutoff (UTC ISO8601):"
if [[ -z "${WINDOW_START:-}" || -z "${WINDOW_CUTOFF:-}" ]]; then
  warn "WINDOW_START and WINDOW_CUTOFF are human-supplied and both required."
  warn "Stopping before any network capture; no evidence was collected."
  exit 1
fi
ask EVAL_WINDOW_RATIONALE "Window rationale (optional, descriptive provenance):"
ask EVAL_WINDOW_POLICY "Window policy name (optional):"

# Validate and canonicalize before any provider call. The validator prints the
# canonical UTC window, its duration, and the rationale, and writes the exact
# validated instants to a small file so no re-parsing can drift the window.
CANONICAL_ENV="$(mktemp)"
WINDOW_RC=0
"${RUN[@]}" "$REPO_ROOT/scripts/validate_evaluation_window.py" \
  --network tron --address "$EVAL_ADDRESS" \
  --start "$WINDOW_START" --cutoff "$WINDOW_CUTOFF" \
  --rationale "${EVAL_WINDOW_RATIONALE:-}" --policy "${EVAL_WINDOW_POLICY:-}" \
  --existing-bundle "$EVIDENCE_ROOT/tron/$EVAL_ADDRESS" \
  --canonical-out "$CANONICAL_ENV" || WINDOW_RC=$?
if [[ "$WINDOW_RC" -ne 0 ]]; then
  rm -f "$CANONICAL_ENV"
  warn "window validation failed (exit $WINDOW_RC); stopping before any provider call"
  exit "$WINDOW_RC"
fi
# shellcheck disable=SC1090
source "$CANONICAL_ENV"
rm -f "$CANONICAL_ENV"
WINDOW_START="$WINDOW_START_UTC"
WINDOW_CUTOFF="$WINDOW_CUTOFF_UTC"
note "using canonical window [$WINDOW_START, $WINDOW_CUTOFF] for $EVAL_ADDRESS"
ask PAGE_LIMIT "Page limit per direction [10]:"
[[ -z "${PAGE_LIMIT:-}" ]] && PAGE_LIMIT=10
ask EVENT_LIMIT "Event limit per direction [200]:"
[[ -z "${EVENT_LIMIT:-}" ]] && EVENT_LIMIT=200
ask MAX_REQUESTS "Max network requests [40]:"
[[ -z "${MAX_REQUESTS:-}" ]] && MAX_REQUESTS=40
if confirm "Run the live capture now (uses network and your TronGrid quota)?"; then
  # The collector reports the actual saved bundle path; never reconstruct it.
  CAPTURE_LOG="$(mktemp)"
  CAPTURE_RC=0
  "${RUN[@]}" "$REPO_ROOT/scripts/collect_behavioral_evidence.py" \
    --candidate "$EVAL_ADDRESS" --token-contract "$TOKEN_CONTRACT" --network tron \
    --start "$WINDOW_START" --cutoff "$WINDOW_CUTOFF" \
    --page-limit "$PAGE_LIMIT" --event-limit "$EVENT_LIMIT" \
    --max-requests "$MAX_REQUESTS" \
    --subject-kind evaluation_wallet --evaluation-registry "$REGISTRY" \
    --evaluation-window-rationale "${EVAL_WINDOW_RATIONALE:-}" \
    --evaluation-window-policy "${EVAL_WINDOW_POLICY:-}" \
    --out-dir "$EVIDENCE_ROOT" | tee "$CAPTURE_LOG" || CAPTURE_RC=$?
  BUNDLE="$(sed -n 's/^bundle_path=//p' "$CAPTURE_LOG" | tail -n1)"
  rm -f "$CAPTURE_LOG"
  if [[ "$CAPTURE_RC" -ne 0 ]]; then
    warn "capture failed (exit $CAPTURE_RC); no bundle was saved"
  elif [[ -n "$BUNDLE" && -f "$BUNDLE/manifest.json" ]]; then
    note "saved bundle: $BUNDLE"
  else
    warn "capture finished but reported no bundle_path; check the output above"
  fi
else
  warn "capture skipped"
fi

# ── Stage 5: verify readiness ─────────────────────────────────────────────
stage "Verify readiness"
say "Materialize the corpus and regenerate the readiness report the console reads."
"${RUN[@]}" "$REPO_ROOT/scripts/materialize_evaluation_dataset.py" \
  --registry "$REGISTRY" --evidence-root "$EVIDENCE_ROOT" --out "$DATASET_OUT"
if confirm "Save the materialized dataset to $DATASET_OUT?"; then
  "${RUN[@]}" "$REPO_ROOT/scripts/materialize_evaluation_dataset.py" \
    --registry "$REGISTRY" --evidence-root "$EVIDENCE_ROOT" --out "$DATASET_OUT" --write
fi
mkdir -p "$(dirname "$READINESS_OUT")"
"${RUN[@]}" "$REPO_ROOT/scripts/evaluation_readiness_report.py" \
  --registry "$REGISTRY" --evidence-root "$EVIDENCE_ROOT" \
  > "$READINESS_OUT"
note "wrote $READINESS_OUT"
say "Re-run this wizard for each additional wallet. Real training/evaluation becomes"
say "possible once the readiness report shows at least 2 distinct materialized wallets."

finish
