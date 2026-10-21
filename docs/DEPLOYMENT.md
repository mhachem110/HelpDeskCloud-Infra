# Infrastructure validation and deployment

## Terraform CI

terraform-ci.yml runs without cloud credentials on pull requests. It validates the promotion route, checks formatting, initializes and validates the core root and both HTTPS roots, runs TFLint on each root, runs Checkov, verifies HTTPS helper shell syntax, and executes the Python guard regression suite.

The former oidc-test and Dev backend-check workflows repeated steps now exercised by the retained Plan and CI workflows. The successful Dev Plan initializes the GCS state through the existing OIDC provider, performs a plan and validates its safety; Terraform CI checks all three roots without live state. They are retired while the provider, service account and bucket permissions remain unchanged.

## Read-only Plan

terraform-dev-plan.yml is manually dispatched from dev and accepts Platform Infrastructure (`core`), HTTPS & Certificates (`https-foundation`) or Identity & Access (`https-access`). It keeps the existing root identifiers, validates the repository and ref, authenticates through the existing GitHub OIDC provider, initializes only the selected state prefix and runs the relevant strict plan guard. The Plan job does not apply changes. Core drift diagnostics are value-safe; HTTPS roots verify the expected hostname, backend and exact user access policy.

## Protected Apply

terraform-dev-apply.yml is manually dispatched. It builds a fresh plan and verifies target selection, project APIs, IAM, drift fingerprint, resource changes and post-apply evidence. The mutating job waits on the protected dev-network-apply Environment and checks the actual GitHub Environment and branch policy before OIDC authentication. Exact deletions, replacements and unapproved changes remain rejected. The workflow never uses a saved plan from an earlier workflow run.

The apply workflow has separate core and HTTPS target paths because they have different Terraform roots, state prefixes, safety checks and read-only verification. Preserve this isolation; merging them into one state or broad permission job would alter resource ownership.

## Evidence and limitations

- [Terraform Dev Apply #45](https://github.com/mhachem110/HelpDeskCloud-Infra/actions/runs/39543113140) succeeded on the verified baseline.
- [Terraform Dev Plan #42](https://github.com/mhachem110/HelpDeskCloud-Infra/actions/runs/39540729992) succeeded with the retained OIDC and GCS backend path.
- [Terraform Dev Backend Check #18](https://github.com/mhachem110/HelpDeskCloud-Infra/actions/runs/39536157570) is historical validation; the standalone workflow is retired.

Local backend-free validation does not prove live state access. A new read-only Plan requires the existing authorized Google identity and access to the existing GCS bucket. No automated Apply or Stage/Prod deployment is enabled.

## Operations and recovery workflows

- **Terraform Drift Detection** runs weekly or by manual dispatch. It selects all three roots on schedule or one explicit root manually, runs read-only Terraform Plans and writes only sanitized action and address summaries. A detected change is a review signal; the workflow never repairs it. This workflow was added and validated offline; no live drift run was performed.
- **Terraform State Health** is manual. It checks the committed bucket/prefix map, bucket versioning and access controls, lifecycle rules, exact state object metadata and available object generations using the existing short-lived Terraform identity. One generation is valid for a new state and is reported without recovery history; two or more provide verified object-version history. It does not initialize Terraform or download state. Its live bucket check has not been run.
- **Terraform Dev Destroy** is manual and defaults to a safe preview. For `core` and `https-foundation`, it inventories state identities and retained `prevent_destroy` safeguards without requesting a Terraform destroy plan. Destroy mode is rejected for those protected roots. For `https-access`, it uses the discovered backend name and configured allowed email to produce a real destroy plan. Future execution requires a pre-existing independent `dev-infra-destroy` Environment, a required reviewer, self-review prevention, dev-only branch restrictions, an explicit `DEV_DESTROY_ENABLED=true`, an exact typed target, a matching fingerprint and root-specific recovery evidence. The repository does not create the Environment or turn on the variable.

All three new workflows refer to the existing WIF provider and service account. Their external WIF workflow-ref allowlist and effective cloud read permissions were not queried or changed; an administrator must verify those prerequisites before a future run. The manually dispatched operational workflows were not run during this cleanup.
