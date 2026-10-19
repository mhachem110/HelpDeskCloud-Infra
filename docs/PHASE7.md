# Phase 7 — Dev GKE Autopilot platform

**Status:** Phase 7 code is merged, but the cluster, identities and secrets have not been deployed. Phase 6's seven resources were deployed and [verified read-only](https://github.com/mhachem110/HelpDeskCloud-Infra/actions/runs/39162768905). The current Dev Plan needs drift review before any Phase 7 Apply.

## What this adds

One regional Autopilot cluster, three Google service accounts, eight narrowly described IAM members, two Secret Manager **metadata** records, and the managed Secret Manager CSI add-on are defined for `dev` only. Terraform creates no secret version or PostgreSQL credential. The existing network, Artifact Registry and Cloud SQL resource addresses are unchanged. `stage` and `prod` use `count = 0` for every new resource and have no authenticated pipeline.

```text
GitHub protected dev + OIDC → Terraform Dev identity → existing locked GCS state
                                         |
                                         +→ Dev GKE Autopilot cluster
                                              | existing Dev VPC/subnet
                                              | existing Pod/Service ranges
                                              | private nodes, DNS control plane
                                              +→ node SA → existing Artifact Registry (Reader)
                                              +→ app KSA/GSA → Cloud SQL Client
                                              +→ migration KSA/GSA → Cloud SQL Client
App Pod → localhost Cloud SQL Auth Proxy --private-ip → VPC/PSA → existing private SQL
App/migration KSA → managed CSI driver → own Secret Manager secret version (later)
```

The cluster uses `module.dev_network[0].vpc_self_link`, `subnet_self_link`, `pods_range_name` and `services_range_name`. The already deployed subnet has `10.20.0.0/20` primary, `10.24.0.0/16` Pods and `10.25.0.0/20` Services. Cloud SQL already uses the VPC's `helpdeskcloud-dev-psa` (`10.30.0.0/16`) allocation. The cluster does not create a second network or SQL connection. The DNS endpoint allows authenticated `kubectl` access from Cloud Shell while the control-plane IP endpoints are disabled. Nodes have private addresses. [GKE network-isolation guidance](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/latest/network-isolation) and the pinned Google provider 7.8.0 schema were checked for these settings; a real cluster response still needs review after approved creation.

## Identities and permissions

| Identity | Scope and purpose | Defined access |
| --- | --- | --- |
| Existing `helpdesk-terraform-dev@...` | GitHub `dev` through existing OIDC; plans/applies the reviewed Terraform | No new grant to this identity in this PR. Owner must review prerequisites below. |
| `helpdesk-gke-node-dev@...` | GKE node system tasks and image pulls | `roles/container.defaultNodeServiceAccount` on project; `roles/artifactregistry.reader` on the existing `helpdeskcloud-dev-images` repository only. |
| `helpdesk-dev-app` KSA → `helpdesk-app-dev@...` GSA | Application Cloud SQL Auth Proxy | `roles/iam.workloadIdentityUser` on this GSA for that KSA; `roles/cloudsql.client` on project. |
| `helpdesk-dev-migrate` KSA → `helpdesk-migrate-dev@...` GSA | One-time schema Job proxy | Same narrow KSA-to-GSA binding on its GSA; project `roles/cloudsql.client`. |
| App and migration KSA principals | Read their own mounted secret through the managed CSI driver | `roles/secretmanager.secretAccessor` on the respective **single secret** only. This is a direct KSA principal grant, separate from GSA impersonation. |
| Future image publisher | Approved one-time Cloud Shell owner identity, then a separate CD identity in Phase 8 | No publisher identity or Writer grant created here. |

The [Autopilot custom node account](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/creating-an-autopilot-cluster), [GKE Workload Identity binding](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/workload-identity), [managed CSI KSA grant](https://docs.cloud.google.com/secret-manager/docs/secret-manager-managed-csi-component), and [Cloud SQL proxy IAM role](https://docs.cloud.google.com/sql/docs/postgres/connect-kubernetes-engine) follow Google's documented patterns. The node identity does not authorize application database access. The Terraform identity is never used in a Pod.

### Owner IAM and API preflight — inspect first, do not auto-grant

Run in Cloud Shell with an approved read-only identity:

```sh
PROJECT=helpdeskcloud-capstone-511905
TF_SA=helpdesk-terraform-dev@$PROJECT.iam.gserviceaccount.com
gcloud services list --enabled --project="$PROJECT" --format='value(config.name)' \
  | grep -E '^(compute|servicenetworking|artifactregistry|sqladmin|container|iam|secretmanager)\.googleapis\.com$'
gcloud projects get-iam-policy "$PROJECT" --format=json > project-iam-review.json
gcloud iam service-accounts get-iam-policy "$TF_SA" --project="$PROJECT" --format=json
gcloud compute networks subnets describe helpdeskcloud-dev-subnet --region=us-east1 --project="$PROJECT"
gcloud sql instances describe helpdeskcloud-dev-postgres --project="$PROJECT"
```

The owner must confirm all **seven** listed APIs are enabled before Plan. Enabling a missing API needs separate approval. The project must have GKE regional cluster/CPU/IP quota, sufficient free subnet IPs and a budget that covers the cost below. The Terraform Dev identity's Phase 5–6 permissions do **not** imply the following Phase 7 rights. Check whether each is already present; grant only after review:

| Operation | Required permission / candidate role | Scope and note |
| --- | --- | --- |
| Create/read/update GKE cluster | `container.clusters.create`, `get`, `update`; commonly `roles/container.admin` | Project. This role is broad; a reviewed custom role is preferable where operationally possible. No auto-grant. |
| Create service accounts | `iam.serviceAccounts.create`, `get`; `roles/iam.serviceAccountAdmin` is a candidate | Project. Also requires `iam.serviceAccounts.getIamPolicy/setIamPolicy` to manage the two KSA impersonation bindings. |
| Attach custom node identity | `iam.serviceAccounts.actAs`; `roles/iam.serviceAccountUser` | Ideally only the new node SA. Because it is created in the same first Apply, validate the bootstrap binding order/approach before Apply; do not grant Token Creator. |
| Set project runtime grants | `resourcemanager.projects.getIamPolicy/setIamPolicy` | Project IAM write is powerful and already used for Phase 5–6; review project policy carefully. |
| Set repository Reader | `artifactregistry.repositories.getIamPolicy/setIamPolicy` | Existing Dev repository only. |
| Create/read secret metadata | `secretmanager.secrets.create/get`; `roles/secretmanager.admin` is a broad candidate | Project for create; resource IAM changes require `secretmanager.secrets.getIamPolicy/setIamPolicy`. Prefer reviewed custom role. Terraform does **not** need `secretmanager.versions.add/access` or payload access. |
| Read-only verification | `container.clusters.get`, `iam.serviceAccounts.get/getIamPolicy`, `secretmanager.secrets.get/getIamPolicy`, plus existing network/SQL/registry/IAM/state reads | For the trusted Dev workflow. It must never read secret payloads. |
| Later Kubernetes install | `container.clusters.get` and Kubernetes namespace/deploy RBAC | Human Cloud Shell identity only after cluster exists; separate from Terraform permissions. |

Read [GKE IAM roles](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/iam), [Service Accounts IAM](https://docs.cloud.google.com/iam/docs/roles-permissions/iam), [Secret Manager IAM](https://docs.cloud.google.com/secret-manager/docs/access-control), and [Artifact Registry IAM](https://docs.cloud.google.com/artifact-registry/docs/access-control) before assigning privileges. A project-scoped role reaches beyond Dev in this single-project capstone; revisit separate projects and state buckets before Stage/Prod. Google-managed GKE service agents are distinct from human and Terraform accounts; do not grant their roles to those accounts.

## Protected Terraform flow

PR CI runs `fmt`, backend-disabled `init`, `validate`, TFLint, Checkov and Python guard tests with `contents: read` only. `terraform-dev-plan.yml` is manual, trusted `dev` and OIDC-backed. `terraform-dev-apply.yml` stays manual and checks the exact repository/ref and protected `dev-network-apply` Environment's required reviewers and **only** `dev` deployment branch. Its saved plan is regenerated after approval and applied exactly, with GCS state locking. `verify-only` is a separate read-only dispatch using the same protected environment.

The guard accepts the original seven as **no-op** and the exact 14 Phase 7 addresses as one creation batch, or all 21 as no-op. It rejects partial creates, updates, deletes, replacements, unknown addresses and drift, except the two previously confirmed provider readbacks (`PSA.labels: null → {}` and subnet `metadata_fields: null → []`) under their existing strict tests. It checks cluster security, IAM principals, secret metadata, and Terraform references. State snapshots and plan JSON stay in the runner's private temporary directory; diagnostics print only approved non-secret classifications. The verifier reads GCP metadata and IAM, outputs and state locally and never uploads raw state or secret versions. **An offline test is not proof that GKE API creation or IAM will succeed.**

### Current drift investigation

The [latest trusted Dev Plan](https://github.com/mhachem110/HelpDeskCloud-Infra/actions/runs/39187250636) proposed **14 additions, no requested updates and no destroys**, but recorded separate readback drift on Artifact Registry `labels` and Cloud SQL `settings.ip_configuration.custom_subject_alternative_names` plus `settings.version`. Its logs contain attribute paths, not the before/after representations. The [provider's Artifact Registry documentation](https://github.com/hashicorp/terraform-provider-google/blob/v7.8.0/website/docs/r/artifact_registry_repository.html.markdown) says `labels` is non-authoritative; its [Cloud SQL documentation](https://github.com/hashicorp/terraform-provider-google/blob/v7.8.0/website/docs/r/sql_database_instance.html.markdown) says custom subject alternative names apply to customer-managed CA and `settings.version` coordinates atomic settings changes. Those descriptions do not establish that this project's observed drift is harmless.

The updated read-only diagnostic classifies the two `labels` maps, confirms whether provider attribution maps are exact and unchanged, reports only a numeric Cloud SQL settings generation, and classifies the certificate mode and subject alternative names without printing arbitrary values. The trusted Dev Plan now runs the **same `check-plan` guard** as Apply after its diagnostic. It should fail until the exact readback is reviewed and a separately tested, narrow allowance is approved. No allowance for these three new paths has been added. Do not dispatch Apply while this guard rejects the plan.

Before an authorized Apply, run the trusted live Dev Plan and review that it says exactly 14 additions and zero updates/deletes, with no unexpected drift. If cloud APIs normalize new fields differently, stop and review rather than loosening the guard. Verify-only requires the new resources to exist, so it is expected to fail before creation.

## Cost estimate before activation

Current [GKE pricing](https://cloud.google.com/kubernetes-engine/pricing) lists $0.10/cluster-hour management and regular general-purpose Autopilot Pod rates of $0.0445/vCPU-hour, $0.0049225/GiB-hour memory and $0.0001389/GiB-hour ephemeral storage. Dev starts with **two replicas**, each with an application container and its own Cloud SQL Auth Proxy sidecar. Per replica, app requests 250m CPU, 512Mi memory and 1Gi ephemeral storage; proxy requests 250m CPU, 256Mi and 1Gi. Together the two Pods request **1 vCPU + 1.5 GiB + 4 GiB**. At those listed rates, both Pods cost about **$0.0524/hour**, **$1.26/day**, **$8.81/7 days**, and **$37.76/30 days** (720 hours), including both proxy sidecars. Limits are higher; billing follows admitted requests and GKE can adjust undersized requests. The chosen totals and ratios are within the [documented Autopilot general-purpose ranges](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/autopilot-resource-requests), but check admitted requests after deployment. Autoscaling remains disabled initially.

[Cloud SQL pricing](https://cloud.google.com/sql/pricing) lists `db-f1-micro` at $0.0105/hour and SSD at $0.000465753/GiB-hour. The **already running** 10 GiB instance contributes about **$0.0152/hour**, **$0.36/day**, **$2.55/7 days**, **$10.91/30 days**, before backup usage and network charges. Together, two app Pods (including both proxy sidecars) plus existing SQL are about **$0.0676/hour**, **$1.62/day**, **$11.36/7 days**, and **$48.67/30 days**, excluding the GKE management fee. Including the full $0.10/hour fee: **$0.1676/hour**, **$4.02/day**, **$28.16/7 days**, and **$120.67/30 days**. The [GKE free-tier credit](https://cloud.google.com/kubernetes-engine/pricing) can offset up to $74.40/month of eligible Autopilot cluster management fees per billing account; it does **not** offset Pod or SQL usage and may already be consumed by another cluster. If fully available, this 30-day example would be about **$48.67** plus usage extras.

The migration Job is short-lived and separately metered. The native managed CSI add-on and IAM/secret metadata have no listed separate hourly price; [Secret Manager](https://cloud.google.com/secret-manager/pricing) has 6 active versions and 10,000 access operations free per billing account/month, then version and access charges. [Artifact Registry](https://cloud.google.com/artifact-registry/pricing) has 0.5 GiB-month storage free per billing account then metered storage; same-region Google Cloud transfer is listed as free. [Logging](https://cloud.google.com/products/observability) has a monthly free allotment then charges, and internet/network egress or support workloads may add cost. These are planning estimates, not a live billing quote; check the project budget and Google calculator before creation. Scaling the app to zero removes its Pod CPU/memory usage but leaves cluster management and SQL charges. Cleanup of GKE later requires a separately approved plan and removal of deletion protection; never destroy the VPC or SQL merely to stop app cost.

## Activation and verification checkpoints

1. **Code review:** merge the Infra and App PRs only after their CI and identifiers agree. This does not deploy anything.
2. **Prerequisites:** owner checks seven APIs, exact Terraform SA rights, GKE quota, private-node Google API access, GitHub Environment review rules, GCS state and current pricing. No API or IAM change is made by the PR.
3. **Cluster:** owner dispatches trusted Dev Plan, checks 14 creates/zero changes/zero deletes and cost, then separately approves the protected Dev Apply. If Apply is partial, stop; the guard deliberately blocks retries. Run `verify-only` or inspect the Apply's read-only verifier. Confirm no public cluster IP endpoint, no new external LoadBalancer, correct private nodes/secondary ranges, IAM scopes and state addresses.
4. **Database:** follow the application repository's `docs/GKE-DEPLOYMENT.md` for owner-controlled login, secret versions and one-time migration. Terraform never receives passwords.
5. **Images and workload:** manually publish vetted images, capture digests and deploy the app only after authorization. The initial two-replica workload remains ClusterIP only and uses local port-forward for a demo.

The verifier proves resource metadata and IAM, **not** working Pod-to-SQL access, CSI mount, application readiness or ticket CRUD. Those live tests belong after Steps 4–5. Phase 8 can add a separately approved application publisher and CD pipeline without expanding Terraform's GitHub OIDC trust to the app repository.
