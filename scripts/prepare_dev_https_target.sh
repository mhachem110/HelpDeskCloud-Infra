#!/usr/bin/env bash
set -euo pipefail

case "${COMPONENT:-}" in
  https-foundation)
    hostname=$(python ../scripts/dev_https_config.py hostname https-foundation/environments/dev.tfvars)
    echo "ready=true" >> "$GITHUB_OUTPUT"
    echo "hostname=$hostname" >> "$GITHUB_OUTPUT"
    ;;
  https-access)
    bash ../scripts/prepare_dev_https_access.sh
    ;;
  *)
    echo '::error::Unknown isolated HTTPS Terraform target.'
    exit 1
    ;;
esac
