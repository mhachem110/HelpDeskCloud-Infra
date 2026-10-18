# Phase 5: Dev networking and IAM foundation

## Scope and architecture

This phase adds Terraform code for a Dev VPC, subnet, GKE secondary ranges, and private services access (PSA). No resources or IAM roles were created during PR development. Stage and Prod keep `module.dev_network` at `count = 0`; their backend files and state are unchanged.

```text
Future GKE Autopilot Pods (10.24.0.0/16)
  -> helpdeskcloud-dev-subnet (nodes: 10.20.0.0/20; Services: 10.25.0.0/20)
  -> helpdeskcloud-dev-vpc (custom mode, REGIONAL routing)
  -> PSA connection using helpdeskcloud-dev-psa (10.30.0.0/16)
  -> future Cloud SQL PostgreSQL private IP
```

The subnet has Private Google Access for private workloads to reach supported Google APIs. It does not give general internet access. A future private-node GKE design must evaluate Cloud NAT if workloads need outbound internet access; [Private Google Access](https://cloud.google.com/vpc/docs/private-google-access) and [Cloud NAT](https://cloud.google.com/nat/docs/overview) serve different destinations. This phase adds neither NAT nor external IP addresses.

The VPC keeps Google's implied ingress deny. No custom firewall rule, public load balancer, database ingress rule, or Cloud SQL public IP is defined. [GKE creates required firewall rules](https://cloud.google.com/kubernetes-engine/docs/concepts/firewall-rules) when a cluster is created; that phase must review those rules and any additional requirements. Checkov's generic CKV2_GCP_18 policy expects a custom firewall on every VPC, so the network resource has a narrow, explained exception. Adding a speculative rule now could interfere with GKE. Subnet flow logs are enabled with 10-minute aggregation, 50% sampling, and no metadata; [logging can incur usage charges](https://cloud.google.com/vpc/docs/flow-logs).

## Address plan and handoff outputs

| Purpose | Name and CIDR | Why it exists | Future consumer |
|---|---|---|---|
| VPC | `helpdeskcloud-dev-vpc` | Global network identity | GKE and Cloud SQL |
| Primary subnet | `helpdeskcloud-dev-subnet`, `10.20.0.0/20` in `us-east1` | Future GKE node addresses | GKE subnet self-link |
| Pod secondary range | `helpdeskcloud-dev-pods`, `10.24.0.0/16` | VPC-native Pod alias IPs | GKE `cluster_secondary_range_name` |
| Service secondary range | `helpdeskcloud-dev-services`, `10.25.0.0/20` | ClusterIP Service addresses | GKE `services_secondary_range_name` |
| PSA allocation | `helpdeskcloud-dev-psa`, `10.30.0.0/16` | Address pool for Google's service producer subnets | Cloud SQL private IP allocation |

These four proposed CIDRs do not overlap **with each other**. Their availability against live project subnets, peerings, routes, and connected networks is unverified. Do not apply until inventory confirms no conflict. Google's [VPC-native GKE guidance](https://cloud.google.com/kubernetes-engine/docs/concepts/alias-ips) supports user-managed Pod and Service ranges; newer Autopilot versions can also use a GKE-managed Service range, but this project deliberately supplies a named range. Google's [Cloud SQL PSA guidance](https://cloud.google.com/sql/docs/postgres/about-private-services-access) recommends a `/16` allocation for growth and requires available `/24` blocks for service producer subnets.

Root outputs are null for Stage and Prod. After an approved Dev apply, `vpc_self_link` and `subnet_self_link` identify the Terraform-managed network and subnet. `pods_range_name` and `services_range_name` identify the GKE secondary ranges. `private_services_range_name` identifies the Cloud SQL allocation. A future Cloud SQL module should reference the VPC self-link and allocation name and depend explicitly on the PSA connection (for example, by consuming `private_services_connection_id` as an input or using `depends_on = [module.dev_network]`). The current PSA resource already references the VPC and reserved range, so Terraform infers that ordering. No GKE-to-Cloud-SQL connectivity is proven until both later resources exist and a real Pod test passes.

## Required read-only inventory before apply

Run in an authenticated Google Cloud Shell with permission to view networking and enabled APIs. Save the results for human review; do not change resources while collecting them:

```bash
PROJECT=helpdeskcloud-capstone-511905
gcloud services list --enabled --project="$PROJECT" --format='value(config.name)' | grep -E '^(compute|servicenetworking)\.googleapis\.com$'
gcloud compute networks list --project="$PROJECT" --format='table(name,autoCreateSubnetworks,routingConfig.routingMode)'
gcloud compute networks subnets list --project="$PROJECT" --format=json
gcloud compute addresses list --global --project="$PROJECT" --format=json
gcloud compute routes list --project="$PROJECT" --format=json
gcloud compute vpn-tunnels list --project="$PROJECT" --format=json
gcloud compute interconnects attachments list --project="$PROJECT" --format=json
# For each existing network returned above:
gcloud compute networks peerings list --network=EXISTING_NETWORK --project="$PROJECT" --format=json
```

Review primary and secondary subnet ranges, allocated PSA ranges, peering and custom-route destinations, VPN and Interconnect attachments, and any connected on-premises address space. Compare them with all four proposed CIDRs and confirm the resource names are unused. Do not silently substitute other ranges if there is a conflict. Compute Engine API was previously enabled, but recheck it. Service Networking API status is unknown. Both APIs must be enabled before a future apply; [Cloud SQL requires both](https://cloud.google.com/sql/docs/postgres/configure-private-services-access). API activation is a separately approved administrator action, not part of this Terraform code.

## IAM permission matrix

| Identity and action | Needed permission or proposed role | Scope and status |
|---|---|---|
| GitHub Actions Dev Terraform service account plans | GCS state access (already proven); Compute read/list/get for network, subnet, global address, routes; Service Networking connection read; Service Usage list | Existing Dev identity; network permissions **not verified**. A plan must fail if access is missing. |
| Same Dev identity in a future approved apply | VPC/subnet create, update, read; global internal address allocation; `servicenetworking.services.addPeering` and related read/list | Evaluate `roles/compute.networkAdmin` on project `helpdeskcloud-capstone-511905`. Google documents it for [PSA creation](https://cloud.google.com/vpc/docs/configure-private-services-access) and includes [addPeering](https://cloud.google.com/iam/docs/roles-permissions/servicenetworking). **Not granted here.** |
| API-state inspection | `serviceusage.services.list` | Project scope. If missing for the Dev identity, evaluate `roles/serviceusage.serviceUsageViewer` for read-only inspection. Do not grant Service Usage Admin merely to plan. [Service Usage IAM](https://cloud.google.com/service-usage/docs/access-control). |
| API enablement, only if disabled | `serviceusage.services.enable` and `servicemanagement.services.bind` | Project/service scope; an authorized administrator must approve and enable APIs separately. Terraform does not manage them. |
| Google-managed Service Networking service agent | `roles/servicenetworking.serviceAgent` | Google-created agent after API enablement. Audit only if peering fails; never grant this role to the Terraform account or an ordinary user. [Service agent guidance](https://cloud.google.com/vpc/docs/configure-private-services-access). |
| Application Pod / Cloud SQL / image pull | Future workload identity, database access method, and Artifact Registry reader permissions | Not needed for Phase 5. Do not put the Terraform account in a Pod. |

The [Cloud SQL PSA permission list](https://cloud.google.com/sql/docs/postgres/configure-private-services-access) includes `compute.globalAddresses.createInternal`, `compute.networks.use`, `servicenetworking.services.addPeering`, and `serviceusage.services.list`. The project-level `roles/compute.networkAdmin` recommendation has reach across **all networking in this single project**, not only Dev. Review that limitation and consider a narrower custom role or future environment projects before production. Owner/Editor/Compute Admin and Service Account Token Creator are not proposed. This PR makes no IAM changes.

Read-only owner commands to inspect current bindings and role contents:

```bash
gcloud projects get-iam-policy helpdeskcloud-capstone-511905 --format=json
gcloud iam roles describe roles/compute.networkAdmin --format=json
gcloud iam roles describe roles/serviceusage.serviceUsageViewer --format=json
```

The GitHub Actions Terraform account is a deployment identity. A later GKE application workload identity and any Cloud SQL access identity have distinct runtime purposes. Artifact Registry image pulling may use a Google-managed GKE node identity or another reviewed identity. Decide those permissions in their own phases; do not reuse the Terraform account.

## Plan workflow and validation

`terraform-dev-plan.yml` is manual-only. The job checks the repository and `dev` ref before OIDC authentication, reuses the Phase 4 Dev backend, and runs `terraform plan -var-file=environments/dev.tfvars`. It does not save a plan artifact, apply, destroy, or grant IAM. It must wait until the owner approves the exact network permissions and verifies both APIs. Do not run privileged plans on feature-branch PR code. Existing credential-free PR CI and backend/OIDC workflows are unchanged.

Offline commands from `terraform/`:

```bash
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate -no-color
tflint --format compact
checkov --directory . --framework terraform --quiet
```

Checkov has one documented firewall exception; the other applicable policies must pass. Offline validation proves HCL structure, not live CIDR availability, API enablement, IAM sufficiency, or successful resource creation. The earlier [Phase 4 backend run](https://github.com/mhachem110/HelpDeskCloud-Infra/actions/runs/39081423878) proves only OIDC and Dev GCS initialization.

## Verification matrix

| Check | When | What it proves |
|---|---|---|
| Offline `fmt`, `init -backend=false`, `validate`, TFLint, Checkov` | PR | Syntax, module wiring, lint and static policy results; no cloud access. |
| CIDR calculation | PR | The four proposed blocks do not overlap each other; not live availability. |
| API and inventory commands above | Before apply | Required APIs and no conflicts with existing network ranges, allocations, routes, or connected networks. |
| Manual Dev plan, with approved IAM | Before apply | Planned changes and enough read permissions; not creation authority or connectivity. Review for exactly one VPC, one subnet, one allocation, and one PSA connection, with no unexpected destroy/replace. |
| `gcloud compute networks describe helpdeskcloud-dev-vpc` | After approved apply | Correct VPC name, custom mode, REGIONAL routing. |
| `gcloud compute networks subnets describe helpdeskcloud-dev-subnet --region=us-east1` | After approved apply | Primary and both named secondary CIDRs, Private Google Access, flow logging. |
| `gcloud compute addresses describe helpdeskcloud-dev-psa --global` | After approved apply | Internal `VPC_PEERING` allocation at `10.30.0.0/16`. |
| `gcloud services vpc-peerings list --network=helpdeskcloud-dev-vpc --service=servicenetworking.googleapis.com` | After approved apply | PSA peering uses the intended VPC and range. |
| Dev backend and IAM review | After approved apply | OIDC and state still use `helpdeskcloud/dev`; approved IAM only; Stage/Prod untouched. |
| Cloud SQL instance inspection | Future Cloud SQL phase | Private IP and **no public database IP**. Not applicable in Phase 5. |
| GKE cluster inspection | Future GKE phase | Cluster uses this VPC, subnet, and named Pod/Service ranges. Not applicable in Phase 5. |
| Pod-to-database test | Future deployment phase | DNS and approved private path reach Cloud SQL; secure `helpdesk-db` Secret provides `ConnectionStrings__Default`; `tickets` schema exists; `/health/ready` passes. Not applicable in Phase 5. |
| Image, ingress, and egress checks | Future deployment phase | Artifact Registry pull works; authenticated HTTPS ingress is approved; outbound access works without unintended exposure. Not applicable in Phase 5. |

Do not manually edit or migrate Terraform state. Do not delete or replace the default VPC.

## Cost impact

The VPC, subnet, internal PSA address reservation, and peering are **typically not standalone hourly compute resources**; [regular VPC network traffic pricing](https://cloud.google.com/vpc/pricing) can still apply to traffic, including peered traffic. [VPC Flow Logs](https://cloud.google.com/vpc/docs/flow-logs) can generate metered telemetry and [Logging charges](https://cloud.google.com/products/observability/pricing) when workloads send traffic. No workload exists in this phase. GKE and Cloud SQL would introduce ongoing compute/capacity charges in later phases. [Cloud NAT](https://cloud.google.com/nat/pricing) would add gateway-hour and data-processing charges if later approved. No NAT, GKE, Cloud SQL, load balancer, or external address is included here. Confirm current project-specific pricing and budget before any apply; do not assume the future system is free.
