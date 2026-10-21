#!/usr/bin/env bash
set -euo pipefail

: "${TARGET_DIR:?TARGET_DIR is required}"
: "${STATE_PREFIX:?STATE_PREFIX is required}"
: "${STATE_BUCKET:?STATE_BUCKET is required}"
: "${PROJECT_ID:?PROJECT_ID is required}"

umask 077
state_file="${RUNNER_TEMP:?RUNNER_TEMP is required}/dev-destroy-state.json"
state_object="gs://${STATE_BUCKET}/${STATE_PREFIX}/default.tfstate"
before=$(gcloud storage objects describe "$state_object" --project="$PROJECT_ID" \
  --format='value(generation)')
[[ "$before" =~ ^[0-9]+$ ]] || { echo '::error::Current state generation is unavailable.'; exit 1; }
terraform -chdir="$TARGET_DIR" state pull > "$state_file"
after=$(gcloud storage objects describe "$state_object" --project="$PROJECT_ID" \
  --format='value(generation)')
[[ "$after" =~ ^[0-9]+$ && "$before" == "$after" ]] || {
  echo '::error::Terraform state changed while its evidence was captured; retry the review.'
  exit 1
}
echo "state_generation=$after" >> "$GITHUB_OUTPUT"
