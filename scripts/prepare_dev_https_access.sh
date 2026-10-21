#!/usr/bin/env bash
set -euo pipefail

not_ready() {
  local reason="$1"
  echo 'ready=false' >> "$GITHUB_OUTPUT"
  echo "::notice::https-access is not ready: $reason"
  echo "### HTTPS access target not ready" >> "$GITHUB_STEP_SUMMARY"
  echo "$reason" >> "$GITHUB_STEP_SUMMARY"
}

if [[ -z "${IAP_ALLOWED_EMAIL:-}" ]]; then
  not_ready 'Set the repository variable DEV_IAP_ALLOWED_EMAIL to the one explicitly selected Google account.'
  exit 0
fi
if [[ ! "$IAP_ALLOWED_EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
  echo '::error::DEV_IAP_ALLOWED_EMAIL must contain exactly one email address.'
  exit 1
fi

gcloud container clusters get-credentials helpdeskcloud-dev-gke \
  --region us-east1 --project helpdeskcloud-capstone-511905 --dns-endpoint

gateway_file="$RUNNER_TEMP/helpdesk-https-gateway.json"
if ! kubectl get gateway helpdesk-dev-https -n helpdesk-dev -o json > "$gateway_file" 2> "$RUNNER_TEMP/helpdesk-gateway-error.txt"; then
  if grep -Eqi 'not found|no resources found' "$RUNNER_TEMP/helpdesk-gateway-error.txt"; then
    not_ready 'The protected HelpDesk Gateway has not been deployed yet.'
    exit 0
  fi
  cat "$RUNNER_TEMP/helpdesk-gateway-error.txt" >&2
  echo '::error::Unable to read the HelpDesk Gateway through the validated GKE DNS endpoint.'
  exit 1
fi

route_file="$RUNNER_TEMP/helpdesk-https-route.json"
if ! kubectl get httproute helpdesk-dev-https -n helpdesk-dev -o json > "$route_file" 2> "$RUNNER_TEMP/helpdesk-route-error.txt"; then
  if grep -Eqi 'not found|no resources found' "$RUNNER_TEMP/helpdesk-route-error.txt"; then
    not_ready 'The HelpDesk HTTPRoute has not been deployed yet.'
    exit 0
  fi
  cat "$RUNNER_TEMP/helpdesk-route-error.txt" >&2
  echo '::error::Unable to read the HelpDesk HTTPRoute through the validated GKE DNS endpoint.'
  exit 1
fi

service_file="$RUNNER_TEMP/helpdesk-https-service.json"
if ! kubectl get service helpdesk-helpdesk -n helpdesk-dev -o json > "$service_file" 2> "$RUNNER_TEMP/helpdesk-service-error.txt"; then
  if grep -Eqi 'not found|no resources found' "$RUNNER_TEMP/helpdesk-service-error.txt"; then
    not_ready 'The HelpDesk application Service or its GKE NEG is not ready yet.'
    exit 0
  fi
  cat "$RUNNER_TEMP/helpdesk-service-error.txt" >&2
  echo '::error::Unable to read the HelpDesk Service through the validated GKE DNS endpoint.'
  exit 1
fi

set +e
backend_name=$(python ../scripts/dev_https_backend.py gateway-backend "$gateway_file" "$route_file" "$service_file")
status=$?
set -e
if [[ "$status" -eq 2 ]]; then
  not_ready 'The HelpDesk Gateway is not yet accepted and programmed by the GKE controller.'
  exit 0
elif [[ "$status" -ne 0 ]]; then
  exit "$status"
fi

backend_file="$RUNNER_TEMP/helpdesk-https-backend.json"
gcloud compute backend-services describe "$backend_name" --global \
  --project helpdeskcloud-capstone-511905 --format=json > "$backend_file"
python ../scripts/dev_https_backend.py validate "$gateway_file" "$route_file" "$service_file" "$backend_file"
echo "ready=true" >> "$GITHUB_OUTPUT"
echo "backend_service_name=$backend_name" >> "$GITHUB_OUTPUT"
echo '### HTTPS access target ready' >> "$GITHUB_STEP_SUMMARY"
echo "The exact programmed HelpDesk Gateway backend was discovered and validated: `$backend_name`." >> "$GITHUB_STEP_SUMMARY"
