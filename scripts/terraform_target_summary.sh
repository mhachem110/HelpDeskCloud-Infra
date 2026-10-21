#!/usr/bin/env bash
set -euo pipefail

target="${1:-}"
operation="${2:-Terraform}"
case "$target" in
  core)
    label='Platform Infrastructure (core)'
    root_path='terraform'
    state_prefix='helpdeskcloud/dev'
    ;;
  https-foundation)
    label='HTTPS & Certificates (https-foundation)'
    root_path='terraform/https-foundation'
    state_prefix='helpdeskcloud/dev-https'
    ;;
  https-access)
    label='Identity & Access (https-access)'
    root_path='terraform/https-access'
    state_prefix='helpdeskcloud/dev-https-access'
    ;;
  *) echo '::error::Unknown Terraform state root.'; exit 1 ;;
esac

{
  echo "## $operation target: $label"
  echo
  echo "Root path: `$root_path`; Terraform root and state identifier: `$target`."
  echo "Existing GCS state prefix: `$state_prefix`."
} >> "${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY is required}"
