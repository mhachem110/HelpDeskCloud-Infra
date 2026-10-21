# Infrastructure code walkthrough

Paths are relative to this repository. The App repo has the companion walkthrough for .NET, Helm, Gateway, IAP and database code.

## Network, data and cluster

- terraform/modules/network/main.tf creates the VPC, subnet, GKE secondary ranges and private services access range. **Trainer answer:** “The module gives the cluster and database one reusable VPC configuration and keeps existing resource addresses stable.” Without the shared network and private service connection, private SQL cannot be reached by the cluster.
- terraform/cloud-sql.tf disables public IPv4, uses the VPC and enables deletion protection. **Trainer answer:** “The database is private, and deletion protection helps keep persistent tickets safe from an accidental Terraform destroy.” A missing private route or proxy identity prevents the app from becoming ready.
- terraform/gke.tf uses Autopilot, private nodes and Workload Identity. It depends on node runtime and Artifact Registry pull grants. **Trainer answer:** “The cluster uses Google-managed Autopilot nodes, and the node identity is ready before cluster creation.” Missing permissions can block node or image startup.
- terraform/gke-iam.tf separates node, app and migration identities. KSA-to-GSA bindings wait for the GKE Workload Identity pool. **Trainer answer:** “The app gets only Cloud SQL Client; a migration has a separate identity so its temporary permissions do not become runtime permissions.”
- terraform/secret-manager.tf provisions metadata and narrowly scoped service-account access. Secret payload values are external. **Trainer answer:** “Terraform wires access without putting database passwords in source or plan outputs.”

## State and identity

- terraform/environments/dev.gcs.tfbackend selects the existing bucket and dev prefix; the two HTTPS roots use their own prefixes. **Trainer answer:** “GCS stores the state remotely and locks concurrent operations. Separate prefixes preserve root ownership; changing them can make Terraform lose the mapping to existing resources.”
- GitHub Actions uses a Workload Identity Federation provider and the existing Dev service account. **Trainer answer:** “OIDC exchanges the GitHub job identity for short-lived Google credentials, so no long-lived key is committed or rotated.”
- terraform/https-access/iam.tf grants roles/iap.httpsResourceAccessor to one user on the selected backend. The project Terraform identity separately retains roles/iap.admin at the owner's explicit request. **Trainer answer:** “The end-user grant is narrowly scoped while the deployment identity retains the owner-approved administrative permission.”

## Plan and Apply

- .github/workflows/terraform-dev-plan.yml authenticates, initializes one state root and runs a guarded read-only Plan. **Trainer answer:** “Plan reports intended changes and drift without modifying infrastructure.”
- .github/workflows/terraform-dev-apply.yml creates a fresh plan, validates exact changes and drift, then waits for the protected dev-network-apply Environment before Apply. **Trainer answer:** “A human approves the current plan, and the guard rejects unexpected deletions or replacements before Terraform can change resources.”
- scripts/dev_infra_guard.py validates plan actions, IAM, state identity, sensitive fields, drift and post-apply evidence. It deliberately has detailed incident regression coverage. **Trainer answer:** “The guard is a policy layer around Terraform's plan JSON; it checks both the proposed change and whether provider readbacks match the known resource.” If an unknown action or identity appears, the job fails closed.
- `provider_identity_checks` centralizes the exact project, pool, provider, status, attribute mapping, CEL condition and resource ID comparison shared by supporting-image, migration and app delivery providers. The refactor removes repeated comparison code; the historical Apply 12 and later recovery checks remain because current validation and regression tests still use them.

## HTTPS foundation

- terraform/https-foundation/https.tf reserves the static address and defines TLS policy, Certificate Manager map, active dynv6 resources and protected legacy FreeDNS resources. **Trainer answer:** “The map contains the active certificate and a deprecated entry retained until a separately approved decommission.”
- terraform/https-access/iam.tf assigns the one approved account access to the exact backend. **Trainer answer:** “IAP is enabled at the backend, and the user role is limited to that backend rather than the whole project.”

## Operations workflow walkthrough

- `.github/workflows/terraform-ci.yml` checks repository configuration offline on pull requests. **Trainer answer:** “CI proves the code and guard checks pass without cloud credentials.”
- `.github/workflows/terraform-drift.yml` runs scheduled or manually selected read-only Plans for the three roots. `scripts/terraform_plan_summary.py` emits only resource addresses and actions. **Trainer answer:** “Drift detection raises a review signal and never repairs the cloud.” No live drift run is claimed here.
- `.github/workflows/terraform-state-health.yml` is manual and inspects bucket settings, object metadata and version history without downloading Terraform state. **Trainer answer:** “The audit checks whether recovery metadata is available while keeping state contents private.” No live state-health run is claimed here.
- `.github/workflows/terraform-dev-destroy.yml` is **implemented for future use — disabled for live destructive execution** and defaults to `plan-only`. It requires stronger gates than Apply because a delete can remove data, network paths and rollback dependencies. SQL deletion protection and certificate `prevent_destroy` stay on; current execution is blocked for those resources. **Trainer answer:** “Destroy needs independent approval, a separate plan review, an exact target and tested recovery evidence.”
- The new `scripts/verify_dev_environment.sh` shares Apply's pre-OIDC check for a pre-existing reviewer-protected, dev-only Environment. Terraform state remains remote in GCS because it is Terraform's resource map and lock coordination; separate prefixes keep root ownership isolated.

The new operational workflows use the existing WIF provider and identity. Their external workflow-ref and cloud permissions were not inspected or changed in this repository-only assignment; verify those prerequisites before any future operational run.

For the application Deployment, internal Service, Gateway, IAP JWT validation and PostgreSQL proxy, see the App repository's docs/CODE-WALKTHROUGH.md.
