# Infrastructure architecture

## Deployed Dev request path

    User
      → helpdeskcloud.dynv6.net DNS
      → Google global HTTPS load balancer at 34.8.56.208
      → Certificate Manager certificate map and TLS 1.2+ policy
      → Google Identity-Aware Proxy
      → GKE Gateway in helpdesk-dev
      → internal helpdesk-helpdesk ClusterIP Service
      → two ASP.NET Core pods and Cloud SQL Auth Proxy sidecars
      → private Cloud SQL PostgreSQL 17

Terraform owns the shared cloud foundation and the three isolated state roots. The App repository owns Kubernetes application and Gateway release manifests. Google IAP is attached to the GKE backend; the app also validates Google's signed identity assertion. The active host is helpdeskcloud.dynv6.net. Its IAP backend service ID is 4800183520372038985.

## Core Terraform root

The terraform/ root manages the Dev VPC, subnet, secondary Pod and Service ranges, private services access, Artifact Registry, Cloud SQL, GKE Autopilot, node and Pod service accounts, Workload Identity grants, and Secret Manager metadata/access. The network module creates one reusable boundary consumed by both GKE and Cloud SQL. Cloud SQL has no public IPv4; private services access connects the service to the VPC. GKE uses private nodes and Workload Identity rather than static service-account keys for Pods.

Secret values, OAuth client credentials and DNS-provider credentials are external inputs. Terraform manages required secret metadata and IAM without storing or printing secret payloads.

## HTTPS foundation and access roots

terraform/https-foundation/ owns the reserved static address, TLS policy, Certificate Manager map, managed certificates and hostname entries. terraform/https-access/ owns the exact user-level IAP role binding on the chosen GKE backend. The active approved user is mahmoud.hachem23743@gmail.com with roles/iap.httpsResourceAccessor on that backend.

The Terraform service account keeps project-level roles/iap.admin at the owner's explicit request. This administrative grant is separate from the narrow application-user grant and must remain.

## Terraform delivery

    Infrastructure PR → Terraform CI
    Manual Plan (core | https-foundation | https-access)
      → GitHub OIDC → matching GCS state prefix → strict plan and drift checks
    Manual Apply (core or selected HTTPS root)
      → fresh plan → protected GitHub Environment → safety guard → apply → read-only checks

The state bucket is helpdeskcloud-tfstate-511905 with independent prefixes helpdeskcloud/dev, helpdeskcloud/dev-https and helpdeskcloud/dev-https-access. Stage and Prod prefixes are prepared but are not deployments. Never rename the bucket or prefixes or move resources between roots without a separate state migration plan.
