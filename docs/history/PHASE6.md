# Phase 6: Dev image registry and private PostgreSQL

## What this PR prepares

Phase 6 adds Terraform definitions for one regional Docker repository, one Cloud SQL PostgreSQL 17 instance, and one named `helpdesk` database. It reuses the four Dev networking resources deployed in Phase 5. This PR creates no cloud resources, changes no IAM, and enables no APIs. Stage and Prod still have zero instances of the new resources.

```text
Future application CI -> Artifact Registry Docker repository
                                |
                         future GKE image pull

Future GKE Pod -> existing helpdeskcloud-dev-vpc
                -> existing Private Services Access connection
                -> Cloud SQL private IP -> helpdesk database
```

Artifact Registry stores Docker images; it does not need a direct VPC attachment. Cloud SQL runs PostgreSQL as a managed service. Version 17 matches the application's local `postgres:17-alpine` database. [Google supports PostgreSQL 17 in Cloud SQL Enterprise](https://cloud.google.com/sql/docs/postgres/choose-edition), including the [shared-core `db-f1-micro` tier](https://cloud.google.com/sql/docs/postgres/machine-series-overview) in [`us-east1`](https://cloud.google.com/sql/docs/postgres/region-availability-overview). This tier is for a small training workload and has no Cloud SQL SLA.

## Terraform files and dependencies

| File | Purpose |
|---|---|
| `terraform/artifact-registry.tf` | Defines the Dev-only private Docker repository. Immutable tags protect future release references. |
| `terraform/cloud-sql.tf` | Defines the Dev-only PostgreSQL instance and named database. |
| `terraform/outputs.tf` | Publishes safe image and database handoff values; values are null for Stage and Prod. |
| `terraform/main.tf` | Keeps the Phase 5 network module at its original `module.dev_network[0]` state address. |
| `terraform/modules/network/` | Still owns the VPC, subnet, private range, and service connection. No duplicate network resources were added. |

The SQL instance's `private_network` reads `module.dev_network[0].vpc_self_link`; `allocated_ip_range` reads `module.dev_network[0].private_services_range_name`. `depends_on = [module.dev_network]` waits for the private services connection, which is an output of that module. The `google_sql_database` resource references the SQL instance name. Google allocates a private IP inside the service producer network reached through [Private Services Access](https://cloud.google.com/sql/docs/postgres/about-private-services-access); `ipv4_enabled = false` prevents a public IPv4 endpoint. The application cannot reach the database until GKE, database authentication, and a real Pod connectivity test exist.

The instance is `POSTGRES_17`, Cloud SQL `ENTERPRISE`, `db-f1-micro`, zonal in `us-east1`, with 10 GiB `PD_SSD`. Storage auto increase is off to prevent unlimited cost growth. If the disk fills, writes can fail; monitor free space and review an explicit increase before it happens. [Google's minimum is 10 GiB](https://cloud.google.com/sql/docs/postgres/instance-settings). The repository is `helpdeskcloud-dev-images` in `us-east1`; a future image path is `us-east1-docker.pkg.dev/helpdeskcloud-capstone-511905/helpdeskcloud-dev-images/helpdeskcloud`. No image is pushed here.

### Backups, logging, and deletion

Daily automated backups begin at 04:00 UTC and retain seven backups. Point-in-time recovery is explicitly off: it needs a separate recovery and storage cost decision. Both Terraform deletion protection and Cloud SQL API deletion protection are on. The named database also has a Terraform `prevent_destroy` guard. This is a single-zone Dev instance without production high availability or a tested restore. A later exercise must restore a backup to prove recoverability. [`log_duration=on`](https://cloud.google.com/sql/docs/postgres/flags) records query durations for diagnosis and generates metered logs; it does not enable full SQL statement logging.

The repository has no automatic deletion policy. [Artifact Registry supports dry-run cleanup policies](https://cloud.google.com/artifact-registry/docs/repositories/cleanup-policy). After image publishing exists, review a policy that retains release tags and several recent versions, test it in dry-run mode, then approve active deletion separately. Immutable tags mean a published release tag must not be moved to a different digest.

### Credentials and application handoff

Terraform creates only the database. It does not create a password-based `helpdesk` user, set the default `postgres` user's password, write a Secret Manager version, run `database/init.sql`, or emit connection strings. Terraform state can contain sensitive resource values even when outputs are marked sensitive, so passwords stay out of this root configuration and GCS state. A later approved database administration procedure should create a restricted `helpdesk` login, store its credential in Secret Manager, audit access and rotation, and securely deliver `ConnectionStrings__Default` through Kubernetes Secret `helpdesk-db` key `connectionString`. The schema must be applied by a controlled migration process; `/health/ready` checks for `public.tickets` and will remain unhealthy until the schema exists.

For GKE, prefer a workload identity separate from the GitHub Terraform identity, with a Cloud SQL Auth Proxy sidecar using the instance connection name and `--private-ip`. The [proxy encrypts and authorizes connections](https://cloud.google.com/sql/docs/postgres/sql-proxy) but still needs a path through the same VPC. The application still needs PostgreSQL authentication; the proxy alone does not create a database user. Future GKE image pull access is another identity and permission decision. The application currently has no end-user login, so keep it private.

## APIs and IAM: owner review before any authenticated plan

The owner previously verified `compute.googleapis.com` and `servicenetworking.googleapis.com` during Phase 5. Artifact Registry and Cloud SQL API status has **not** been verified here because this workspace has no authenticated `gcloud`. In Google Cloud Shell, run read-only checks:

```bash
PROJECT=helpdeskcloud-capstone-511905
gcloud services list --enabled --project="$PROJECT" --format='value(config.name)' | grep -E '^(artifactregistry|sqladmin|compute|servicenetworking)\.googleapis\.com$'
gcloud artifacts repositories list --project="$PROJECT" --location=us-east1
gcloud sql instances list --project="$PROJECT"
gcloud projects get-iam-policy "$PROJECT" --format=json
```

If either new API is disabled, the owner must separately approve its activation. Do not enable it through this Terraform configuration. Confirm the existing PSA connection is active and has free address space before a later apply. Google-managed service agents may be created when APIs are enabled; grant service-agent roles only to their corresponding Google-managed identities if official troubleshooting requires it.

| Identity/action | Permissions or role to review | Scope and caution |
|---|---|---|
| Dev Terraform state | GCS bucket object read/write and locking permissions | Existing `helpdeskcloud-tfstate-511905` bucket access is verified. Prefixes alone do not isolate Stage/Prod. |
| Dev Terraform reads Artifact Registry | `artifactregistry.repositories.get`, `artifactregistry.repositories.list` | Project read access must cover discovery of a repository not yet created. |
| Dev Terraform creates/manages repository | `artifactregistry.repositories.create`, `get`, `update`, `delete`; consider `roles/artifactregistry.admin` | [Google recommends project-scoped Admin for repository creation](https://cloud.google.com/artifact-registry/docs/repositories/create-repos). It also grants broad artifact powers; review a custom role for narrower reach. |
| Dev Terraform reads Cloud SQL | `cloudsql.instances.get`, `list`; `cloudsql.databases.get`, `list` | Project-level Cloud SQL permissions. |
| Dev Terraform creates/manages SQL and database | `cloudsql.instances.create`, `get`, `list`, `update`; `cloudsql.databases.create`, `get`, `list`, `update`; consider `roles/cloudsql.admin` | [Cloud SQL permissions](https://cloud.google.com/sql/docs/postgres/iam-permissions) are project-scoped. Admin also permits delete, user and backup management; review a custom role if practical. |
| Existing Dev VPC/PSA inspection | Compute Network Viewer and Service Networking read permissions already used in Phase 5 | Recheck actual bindings and failed-plan messages. No new network admin grant is proposed. |
| Future image publisher / GKE image consumer | `roles/artifactregistry.writer` / `roles/artifactregistry.reader` | Grant on the **repository** after creation, to separate approved identities. No `allUsers` binding. |
| Future GKE SQL proxy / application | `roles/cloudsql.client` for an approved GKE workload identity, plus a restricted PostgreSQL login | Separate from the GitHub Terraform service account. Not created here. |

Do not assume the Dev Terraform service account has the new permissions. The owner must review exact grants and scope before a privileged plan. Do not grant Owner, Editor, general Compute Admin, or Service Account Token Creator as a shortcut. This single-project architecture means project-level Cloud SQL and repository-create permissions span more than the Dev environment.

## Cost estimate, as of October 2026

[Cloud SQL list pricing](https://cloud.google.com/sql/pricing) shows `db-f1-micro` at **$0.0105/hour**, SSD capacity at approximately **$0.000232877/GiB-hour**, and used backup storage at approximately **$0.000109589/GiB-hour** in the displayed US pricing tables. These are estimates for one always-on zonal instance, 10 GiB SSD, and 1 GiB of used backups, without taxes, discounts, credit application, extra logs, or network egress:

| Component | 24 hours | 30 days (720 hours) |
|---|---:|---:|
| Shared-core compute | $0.25 | $7.56 |
| 10 GiB SSD | $0.06 | $1.68 |
| 1 GiB used backup storage | < $0.01 | $0.08 |
| **Illustrative total** | **~$0.31** | **~$9.32** |

If backups use 10 GiB continuously, the estimate rises to about **$0.33/day** or **$10.03/30 days**. Backup usage and logs vary; cross-region or internet traffic can add charges. Confirm `us-east1` rates in the [Google Cloud Pricing Calculator](https://cloud.google.com/products/calculator) and the project's billing view before deployment. A budget alert does not cap spending.

[Artifact Registry pricing](https://cloud.google.com/artifact-registry/pricing) includes the first 0.5 GiB-month of storage free per billing account, then about $0.10/GiB-month. Example: 2 GiB stored for a month is about $0.15 after that free allowance, if unused elsewhere on the billing account. Uploads are free; same-region pulls to GKE are listed as free, while other transfer and optional scanning can cost money.

When the Dev instance is not needed, the owner can review an approved stop through [Cloud SQL's activation policy](https://cloud.google.com/sql/docs/postgres/start-stop-restart-instance) (`NEVER`), after checking application impact and reconciling Terraform to avoid drift. Stopping ends compute charges while [provisioned storage and used backups remain billable](https://cloud.google.com/sql/docs/postgres/faq). Do not automate destruction. Eventual cleanup requires a tested backup/export and explicit acceptance of permanent data loss; deletion protection must be deliberately reviewed first.

## Pipeline behavior and safe deployment path

`terraform-ci.yml` remains credential-free and checks formatting, initialization without GCS, Terraform validation, TFLint, Checkov, promotion routes, and now the existing Python Apply guard tests. `terraform-dev-plan.yml` remains a manual, trusted-`dev` workflow; its labels now describe all Dev infrastructure. It can run **only after** API and IAM review, and permission failures must fail the job.

`terraform-dev-apply.yml` is the single protected Dev infrastructure Apply path. Its `dev_infra_guard.py` accepts only the exact four existing network addresses as unchanged and the three Phase 6 addresses as a complete set of creations. It rejects partial creation, unexpected addresses, updates, replacements, deletions, and all drift except the two exact provider readback differences below. When all seven are already present with no changes, it returns `no_changes` and skips Apply. It checks planned settings and Terraform references, including SQL's links to the existing VPC and PSA range. Read-only preflight checks require all four APIs enabled and reject direct public project IAM bindings before approval; project IAM is rechecked after approval. The `dev-network-apply` GitHub Environment name remains unchanged because the existing OIDC binding depends on it. Required reviewers, the sole `dev` deployment branch policy, trusted repository/ref checks, and the fresh saved plan after approval remain in place. No generic Apply path exists.

The [later failed Dev Apply run](https://github.com/mhachem110/HelpDeskCloud-Infra/actions/runs/39153574581) planned **3 to add, 0 to change, 0 to destroy**. Its diagnostic identified exactly two `resource_drift` entries: `module.dev_network[0].google_compute_global_address.private_services` at `labels`, and `module.dev_network[0].google_compute_subnetwork.this` at `log_config[0].metadata_fields`. Both drift entries reported `update`, while the proposed infrastructure operations contained no updates. The owner separately verified that the address state has `labels = null` and `terraform_labels = {goog-terraform-provisioned = true}` while GCP reports that label, and that subnet state has `metadata = EXCLUDE_ALL_METADATA`, `metadata_fields = null` while GCP displays no metadata fields. The [Google provider reference](https://registry.terraform.io/providers/hashicorp/google/7.8.0/docs/guides/provider_reference) documents the attribution label; the [subnetwork resource reference](https://registry.terraform.io/providers/hashicorp/google/7.8.0/docs/resources/compute_subnetwork) says `metadata_fields` applies only with `CUSTOM_METADATA`. These facts support a provider readback explanation, but the failed run did **not** print the exact structured plan before/after values.

The guard now allows the address drift only if its complete before and after snapshots are identical except for `labels: null` becoming exactly `{goog-terraform-provisioned: true}`, with `terraform_labels` unchanged at that exact map. It allows the subnet drift only if the snapshots are identical except for `log_config[0].metadata_fields` moving between null, missing, or an empty list while `metadata` remains `EXCLUDE_ALL_METADATA`. It rejects any other drift, including extra labels, nonempty metadata fields, changes to metadata mode, CIDRs, resource identity, VPC, or peering. The real JSON representation must match these exact conditions; otherwise Apply stays blocked. The existing plan guards separately require unchanged network resources and exactly three complete Phase 6 additions or zero changes. `resource_changes` describes requested operations; `resource_drift` records a separate difference between stored state and live GCP. A plan summary alone does not settle the drift question.

After this change reaches protected `dev`, run the manual **Terraform Dev Plan** workflow. It uses the existing OIDC connection and Dev GCS backend. Its existing diagnostic now additionally reports only safe representations of the two known fields (`null`, `missing`, `[]`, or the exact attribution label); any unexpected value is withheld. It does not publish plan JSON, state, or other before/after values. Check that the report shows only these two paths and that the actual structured values satisfy the guard before considering Apply. If deeper inspection is necessary, an authorized owner can run `terraform show -json` on a saved plan in a private Cloud Shell session and keep the JSON and state out of tickets, logs, and PRs. Any other drift requires investigation and a separate review.

The safe later sequence is: merge reviewed code to `dev`; confirm API status and approved Dev service-account permissions; run the trusted Dev Plan diagnostic and review the two exact representations; inspect the fresh plan for exactly **three additions** and no network changes; review the approximately $9–$10/month Cloud SQL cost and get the owner's explicit deployment authorization; dispatch protected Dev Apply; approve its existing GitHub Environment gate; let it regenerate and validate a fresh saved plan; apply only that saved plan; verify all seven live resources and state. A saved plan is regenerated after approval because remote state or cloud reality may have changed while approval was pending. This PR does not perform any cloud changes.

## Validation and future verification

From `terraform/`, run:

```bash
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate -no-color
tflint --format compact
checkov --directory . --framework terraform --quiet
```

From the repository root, run `python -m unittest discover -s scripts -p 'test_*.py' -v` and Actionlint on changed workflows. These checks prove structure and policy compliance, not GCP permission, provider API acceptance, live state safety, or connectivity.

After a separately approved deployment, the workflow uses read-only `gcloud` output to verify the VPC, subnet, ranges, Private Google Access, active PSA peering, repository name/region/Docker format/immutable tags, repository and project IAM policies for direct public bindings, PostgreSQL 17 Enterprise `db-f1-micro`, 10 GiB SSD, backups, both deletion protections, private IP, **no public IP**, the VPC and allocated range, and the `helpdesk` database. It compares `terraform state list` against exactly four network addresses plus three Phase 6 addresses and checks relevant outputs against the live values. The project/repository IAM inspection requires `resourcemanager.projects.getIamPolicy` and `artifactregistry.repositories.getIamPolicy`; API status listing requires `serviceusage.services.list`. If a read-only permission is missing, verification fails and the owner must review that exact scope; the workflow grants nothing. Direct policy checks cannot prove the absence of every indirect or conditional access path, so an owner should also review effective IAM. Confirm Stage/Prod state untouched. A restore test is still needed to verify backups.

Phase 7 must provision GKE on the existing subnet and named Pod/Service ranges, arrange secure image pulls, create a dedicated workload identity and Cloud SQL Auth Proxy integration, establish a restricted database user and secret delivery, run controlled schema migrations, and verify `/health/ready` from a Pod. Public ingress needs an approved HTTPS and end-user authentication design. None of these end-to-end tests is complete in Phase 6.
