#!/usr/bin/env bash
set -euo pipefail

# This helper is scoped to the existing Dev Apply Environment. It checks that
# its reviewer gate and dev-only branch rule exist before the job receives OIDC.
test "${REPOSITORY:-}" = "mhachem110/HelpDeskCloud-Infra"
test "${REF:-}" = "refs/heads/dev"
test "${EXPECTED_ENVIRONMENT:-}" = "dev-network-apply"
command -v jq >/dev/null

environment_file="${RUNNER_TEMP:?}/dev-environment.json"
branches_file="${RUNNER_TEMP:?}/dev-branches.json"
url="https://api.github.com/repos/mhachem110/HelpDeskCloud-Infra/environments/$EXPECTED_ENVIRONMENT"

curl -fsSL --retry 3 -H 'Accept: application/vnd.github+json' \
  -H "Authorization: Bearer ${GH_TOKEN:?}" "$url" > "$environment_file" || {
    echo '::error::GitHub Environment API request failed; no cloud authentication was attempted.'
    exit 1
  }
curl -fsSL --retry 3 -H 'Accept: application/vnd.github+json' \
  -H "Authorization: Bearer ${GH_TOKEN:?}" \
  "$url/deployment-branch-policies?per_page=100" > "$branches_file" || {
    echo '::error::GitHub deployment branch policy request failed; no cloud authentication was attempted.'
    exit 1
  }

jq -e --arg expected "$EXPECTED_ENVIRONMENT" \
  '.name == $expected and .deployment_branch_policy.custom_branch_policies == true and ([.protection_rules[]? | select(.type == "required_reviewers" and (.reviewers | length) > 0)] | length) > 0' \
  "$environment_file" >/dev/null
jq -e '.total_count == 1 and (.branch_policies | length) == 1 and .branch_policies[0].name == "dev"' \
  "$branches_file" >/dev/null
echo "Pre-existing $EXPECTED_ENVIRONMENT reviewer protection and dev-only branch policy verified."
