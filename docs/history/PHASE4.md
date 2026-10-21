# Phase 4: Terraform infrastructure foundation

## Objective and scope

Phase 4 makes the infrastructure repository ready for reviewed Terraform changes. One root configuration serves Dev, Stage, and Prod through separate variable and backend files. This phase validates configuration and tests the existing Dev OIDC path. It does not create, import, or modify GCP resources.

## Bootstrap components reused

The project `helpdeskcloud-capstone-511905` (number `260283083469`), state bucket `helpdeskcloud-tfstate-511905`, Workload Identity Pool `helpdesk-github`, provider `github-infra-dev`, and service account `helpdesk-terraform-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com` already exist. The service account has bucket-level Storage Object Admin and a working Workload Identity User binding. The [earlier OIDC test](https://github.com/mhachem110/HelpDeskCloud-Infra/actions/runs/39076298011) proved GitHub authentication and bucket access on `dev`. This work does not alter those relationships.

The provider maps GitHub's subject, repository, and ref claims. Its condition accepts only `mhachem110/HelpDeskCloud-Infra` on `refs/heads/dev`. The working immutable-subject identity is `repo:mhachem110@150286776/HelpDeskCloud-Infra@1423008553:ref:refs/heads/dev`. An older non-immutable binding may still exist; its removal needs a separate IAM audit. Phase 4 did not change IAM.

The standalone `oidc-test.yml` and `terraform-dev-backend.yml` checks described in the original phase were later retired. The retained manual Dev Plan workflow now proves OIDC authentication, initializes the existing state and exercises Terraform validation; Terraform CI validates all three roots without live credentials.

## Architecture and authentication flow

```text
feature PR -> credential-free Terraform CI -> review -> protected dev merge
                                                        |
                                                        v
dev GitHub Actions -> GitHub OIDC -> existing Workload Identity provider
                   -> Dev service account -> existing GCS bucket
                   -> helpdeskcloud/dev Terraform state prefix
```

`backend.tf` declares a partial `gcs` backend. `terraform init` combines it with `environments/dev.gcs.tfbackend`, which has only the bucket and prefix. The auth action makes short-lived Application Default Credentials available to Terraform. No service account key is stored. `providers.tf` uses the project and region from `dev.tfvars` when operations require provider configuration. The backend check initializes and validates only; it does not apply.

The Stage and Prod backend files have their own prefixes. This separates object names, **not** permissions. The current Dev identity has bucket-level object access and could access future Stage/Prod state objects in the same bucket. Do not enable Stage or Prod state operations until separate state buckets or another reviewed IAM isolation design is in place.

## Exact validation commands

From the repository root on a machine with Terraform 1.16.2, TFLint, Checkov, and Python YAML support:

```sh
cd terraform
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate -no-color
tflint --format compact
checkov --directory . --framework terraform --quiet
```

The CI workflow runs those Terraform checks independently. It does not need cloud access. To test the real Dev remote backend from an approved authenticated environment:

```sh
cd terraform
terraform init -input=false -no-color -lockfile=readonly -backend-config=environments/dev.gcs.tfbackend
terraform validate -no-color
```

If a previous local initialization selected another backend, add `-reconfigure` only after checking which state you intend to use. Never use `-migrate-state` casually. Do not use `apply` or `destroy` in this phase.

## GitHub Actions

`terraform-ci.yml` runs on every PR targeting `dev`, `stage`, or `prod`. Its route job accepts `feature/* → dev`, `dev → stage`, and `stage → prod`. Separate jobs check formatting plus initialization and validation, TFLint, and Checkov. All jobs have repository read permission only; no PR job receives an OIDC token. Checkov scans the Terraform directory. There are no resources yet, so resource security findings become meaningful as resources are added.

`terraform-dev-backend.yml` runs on relevant pushes to `dev`, or manual dispatch with a `dev` ref. The job also checks the ref and repository. After checkout, it uses the existing OIDC provider and service account, initializes with `dev.gcs.tfbackend`, and validates. Its only elevated GitHub permission is `id-token: write` for that job. It cannot run authenticated on a feature-branch PR. `oidc-test.yml` is unchanged.

## Verification record

The repository's earlier OIDC smoke test verified authentication and bucket access, but it did **not** initialize Terraform's GCS backend. Local format, offline init, validate, lint, scan, YAML, and ignore checks are recorded in the Phase 4 PR. The new authenticated backend check can be verified only after approved merge to `dev`, when the existing provider condition allows its OIDC subject. Do not describe backend connectivity as verified until that workflow succeeds.

## Known limits and Phase 5 prerequisites

- Review state IAM boundaries. The Dev service account currently has access across the shared bucket; prefixes alone cannot protect Stage or Prod. Decide on separate buckets or another enforceable isolation solution before those environments are operational.
- Confirm the existing bucket's versioning and recovery policy in a separate read-only audit. Do not change the bucket in Phase 4.
- Audit and remove the obsolete non-immutable identity binding only after independently verifying it exists and approving an IAM change.
- Define Phase 5 Networking and IAM resources, naming, least-privilege roles, costs, and review gates before implementing them.
- Design separate Stage and Prod identities, OIDC providers or conditions, state access, and deployment approvals before enabling authenticated promotion.
- Keep GKE, Cloud SQL, Artifact Registry, Secret Manager, and Kubernetes deployment work for their later phases.
