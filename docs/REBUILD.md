# Infrastructure rebuild runbook

This describes dependency order for a replacement Dev environment. It is not approval to destroy or recreate the deployed project. Keep current GCS state, Cloud SQL data, GKE, DNS, certificates, secrets and ticket records intact. Any replacement plan or state recovery needs owner review before a mutating action.

## External prerequisites

You need an authorized Google Cloud project administrator, the existing project and billing, the current state bucket and backend prefixes, repository administration for protected Environments and OIDC settings, and control of the selected DNS hostname. OAuth client ID/secret, the approved Google account and DNS-provider credentials are external inputs, not stored in Git. Terraform 1.16.2 and the committed provider lock files are required.

## Dependency order

1. **Project and APIs:** Confirm project helpdeskcloud-capstone-511905 and project number 260283083469. Confirm Compute, Service Networking, Artifact Registry, Cloud SQL Admin, GKE, IAM, Secret Manager, Certificate Manager and IAP APIs. Use an administrator for one-time API enablement.
2. **Terraform state:** Confirm bucket helpdeskcloud-tfstate-511905 and existing prefixes helpdeskcloud/dev, helpdeskcloud/dev-https and helpdeskcloud/dev-https-access. Do not initialize a replacement state or copy state over the live prefixes.
3. **Core network:** Review the terraform/ plan for the existing VPC, subnet, secondary ranges and private services access. Preserve all resource addresses and CIDRs. The network is a dependency for private Cloud SQL and GKE.
4. **Artifact Registry and Cloud SQL:** Review the core plan and retain repository immutability, private PostgreSQL connectivity, backups and deletion protection. Cloud SQL must use the VPC's private services connection and have no public IPv4.
5. **GKE Autopilot:** Create or verify the cluster on that VPC, with private nodes, configured Pod identity pool and Secret Manager CSI integration. Keep the existing node service account and image pull permissions.
6. **Workload Identity and IAM:** Verify distinct node, app and migration service accounts. The app and migration KSA-to-GSA bindings depend on the cluster pool existing. Keep least privilege for Pods and preserve the Terraform identity's owner-approved project-level roles/iap.admin.
7. **GitHub OIDC:** Confirm exact repository, ref and workflow filename conditions for all existing WIF providers and separate publication/deployment identities. Use GitHub Environments and short-lived OIDC credentials; do not create service-account keys.
8. **Secret Manager:** Through approved bootstrap, create required secret payload versions without displaying them. Apply IAM only to the intended namespace service accounts. Terraform holds metadata and access bindings; the secret values remain external.
9. **Application Kubernetes prerequisites:** Follow the App repository's Rebuild guide to create namespace helpdesk-dev, apply delivery and migration Roles/RoleBindings, publish the supporting image digests, and run a reviewed application release. The RBAC manifests are namespace-scoped and include Gateway and GKE policy resources.
10. **Database schema:** Confirm private proxy connectivity. For a genuinely empty replacement database, use the separately approved migration workflow and documented schema. Never rerun initial schema SQL on the current live database; later changes use versioned migrations.
11. **HTTPS foundation:** Plan the https-foundation root and retain the static IP, TLS policy, Certificate Manager map and active managed certificate. Publish the DNS authorization record at the external DNS provider and wait for certificate readiness.
12. **OAuth and IAP:** Configure the OAuth client and secret outside Git. Grant the approved user roles/iap.httpsResourceAccessor only on the intended backend. Keep the broader project IAP Admin role on the Terraform identity at the owner's request.
13. **Backend and JWT audience:** Discover the exact GKE backend after the Gateway exists. The current backend ID is 4800183520372038985. Configure the application with the canonical IAP audience and the approved email. Preserve signature, issuer, audience and email validation.
14. **HTTPS access and Gateway:** Run the https-access Plan only after the backend is present. Follow the App runbook to install the edge Helm release with hostname helpdeskcloud.dynv6.net, IP 34.8.56.208, map helpdesk-dev-https-map and TLS policy helpdesk-dev-https-tls. Expose HTTPS 443 only.
15. **DNS and verification:** Confirm DNS resolves to the reserved address and use ordinary TLS verification. Test approved login, denial for an unauthorized Google identity, anonymous ticket API denial, app health, ticket creation and persistence. Record run links and image digests, never credentials or ticket contents.

The app repository's [rebuild runbook](https://github.com/mhachem110/HelpDeskCloud-App/blob/dev/docs/REBUILD.md) has the detailed 16-step app and Kubernetes procedure. Stage and Prod remain prepared environments, not live deployments.

## Future teardown order

This is a planning sequence, not authorization to remove the running Dev environment. The future-only Terraform Dev Destroy workflow defaults to an inventory preview for protected `core` and `https-foundation` roots, and a read-only destroy plan for `https-access`. It rejects destroy mode for roots with retained SQL or certificate protections. Any teardown requires a separately reviewed matching fingerprint, verified restore-tested backups, a protected `dev-infra-destroy` Environment and an explicit opt-in prepared outside this repository.

1. Stop future application releases and database migrations; record the current image digests and workflow evidence.
2. Preserve and verify Cloud SQL backups and application data. Complete a restore exercise before database removal.
3. Remove the application and HTTPS edge Helm releases using a separate authorized App operation; no Terraform workflow removes Kubernetes objects.
4. Review and remove the exact IAP backend access grant, then review Gateway, DNS, certificate, TLS policy and reserved address dependencies.
5. Remove core network, cluster, registry and identity resources last, after app, edge and database dependencies are resolved.
6. Retain all Terraform state and versioned recovery copies. Never destroy the state bucket through a workflow whose state is stored in that bucket.

Rollback requires the state bucket, state generations, image digests, database backup and external DNS/OAuth inputs. Certificate `prevent_destroy` and Cloud SQL deletion protection are deliberate stops until a separate plan demonstrates that data and shared certificate dependencies are safe to remove.
