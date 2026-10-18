# HelpDesk Cloud infrastructure

HelpDesk Cloud is an ASP.NET Core .NET 10 ticketing application with PostgreSQL storage. The [application repository](https://github.com/mhachem110/HelpDeskCloud-App) holds its code, container, and Helm chart. This repository holds cloud infrastructure so application changes and infrastructure changes can be reviewed and promoted separately.

The existing Google Cloud project is `helpdeskcloud-capstone-511905`; the target region is `us-east1`. Phase 4 established Terraform and the Dev GCS backend. The [Phase 5 Dev network was deployed and verified](https://github.com/mhachem110/HelpDeskCloud-Infra/actions/runs/39146464396). Phase 6 defines a Docker repository and private PostgreSQL database for a later approved deployment. GKE and application workloads are future work.

## Repository map

```text
.github/workflows/
  oidc-test.yml              Existing successful OIDC smoke test
  terraform-ci.yml           Credential-free PR checks
  terraform-dev-backend.yml  Dev-only authenticated backend check
  terraform-dev-plan.yml     Manual Dev infrastructure plan (after IAM review)
  terraform-dev-apply.yml    Protected, network-only Phase 5 Apply guard
scripts/
  dev_network_guard.py       Checks plan JSON and post-apply evidence
  test_dev_network_guard.py  Offline tests for the Apply safety gate
terraform/
  backend.tf                 Partial GCS backend declaration
  versions.tf                Terraform and Google provider versions
  providers.tf               Google project and region settings
  variables.tf               Three required input values
  locals.tf                  Reusable environment identifier
  main.tf                    Deployed Dev network module call; unchanged state addresses
  artifact-registry.tf       Dev-only Docker repository definition
  cloud-sql.tf               Dev-only PostgreSQL instance and helpdesk database
  outputs.tf                 Safe configuration, network, registry, and SQL handoff values
  .terraform.lock.hcl        Locked provider checksums
  environments/
    dev.tfvars               Dev project, environment, and region
    stage.tfvars             Stage project, environment, and region
    prod.tfvars              Prod project, environment, and region
    dev.gcs.tfbackend        Existing state bucket; Dev prefix
    stage.gcs.tfbackend      Existing state bucket; Stage prefix
    prod.gcs.tfbackend       Existing state bucket; Prod prefix
  modules/network/           Reusable VPC, subnet, and private services access
  modules/README.md          Module inventory
docs/PHASE4.md               Commands, verification, and Phase 5 prerequisites
docs/PHASE5.md               Network plan, IAM, inventory, costs, verification
docs/PHASE6.md               Registry and SQL design, credentials, costs, rollout gates
```

## Terraform and state

All environments use the same root configuration. A `.tfvars` file selects project, region, and environment. A `.gcs.tfbackend` file selects the existing bucket and an environment-specific prefix. `terraform init -backend-config=...` reads the backend file. The prefixes are `helpdeskcloud/dev`, `helpdeskcloud/stage`, and `helpdeskcloud/prod`. We do not use Terraform workspaces for environment separation.

GCS stores Terraform state remotely and supports locking. State may contain sensitive infrastructure data, so `.gitignore` excludes local state, plans, Terraform downloads, and generated GitHub OIDC credential files. Commit the provider lock file; do not commit state. The Dev service account currently has **bucket-level** Storage Object Admin. Separate prefixes do **not** provide IAM isolation. Stage and Prod backend files are prepared, but authenticated access for them is deliberately not enabled. Before real Stage or Prod use, review separate state buckets or another enforceable IAM boundary.

GitHub Actions authenticates to Google Cloud through the existing Workload Identity Federation provider and Dev service account, using short-lived credentials rather than service account keys. The provider admits this repository on `refs/heads/dev`. The existing `oidc-test.yml` remains intact. PR validation uses no GCP credentials. The new Dev backend workflow runs on trusted `dev` and can be dispatched only into its Dev job when the selected ref is `dev`.

## Local validation

Install Terraform 1.16.2 and run these commands from `terraform/`:

```sh
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate
tflint --format compact
checkov --directory . --framework terraform --quiet
```

These commands do not connect to GCS. For a real Dev backend initialization, authenticate locally with an approved Google Cloud identity that can access the state bucket, then run:

```sh
terraform init -input=false -backend-config=environments/dev.gcs.tfbackend
terraform validate
```

Local Application Default Credentials can be used; no key file is required. A local `terraform init` can replace the cached backend settings in `.terraform/`, so use `-reconfigure` when deliberately switching backend configuration. Do not initialize Stage or Prod with the Dev identity.

`terraform fmt -check`, `terraform init -backend=false`, `terraform validate`, TFLint, and Checkov are safe validation commands. Run `python -m unittest discover -s scripts -p 'test_*.py' -v` from the repository root to check the Phase 5 Apply guard. The manual Dev Plan workflow can show all Terraform changes after the required API and IAM review. The existing protected Apply workflow still permits only the four Phase 5 networking resources and will reject Phase 6 additions. It must be upgraded in a separate reviewed change before any approved registry or SQL deployment. See [Phase 6 notes](docs/PHASE6.md). Do **not** run `terraform apply`, `terraform destroy`, state migration, or any resource-changing command without explicit owner approval and a reviewed phase plan.

## Branch flow

Changes move through protected branches: `feature/*` → `dev` → `stage` → `prod`. The PR workflow checks those source and target pairs. Merging to `dev` triggers the Dev backend check when Terraform or that workflow changes. It does not apply resources. Stage and Prod deployment identities, permissions, approvals, and pipelines are future work.

See [Phase 4 notes](docs/PHASE4.md) for the established foundation, [Phase 5 notes](docs/PHASE5.md) for the network design and IAM limits, and [Phase 6 notes](docs/PHASE6.md) for database and registry settings, cost estimates, and deployment prerequisites.
