# Dev Terraform drift review

The **Terraform Dev Plan** workflow is read-only. It reports resource drift and the
exact changed field paths, then continues through the normal plan-safety checks.
Seeing drift in this workflow does not approve or apply an infrastructure change.

For an intentional managed-resource update, the diagnostic prints a
`drift-v1-…` fingerprint built from resource addresses, action types, and changed
field paths. It contains no before/after values. Enter that exact fingerprint in
the `acknowledged_drift_fingerprint` input when dispatching **Terraform Dev Apply**.
The fingerprint must still match both the pre-approval plan and the fresh
post-approval plan.

The acknowledgement only covers known managed updates. Unknown resources,
malformed drift, deletions, and replacements remain blocked. Secret Manager IAM
drift still requires live policy evidence to match the principals and roles in
Terraform state. The existing plan shape checks and the protected
`dev-network-apply` Environment reviewer remain required.
