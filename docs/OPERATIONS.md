# Operations and retained resources

## Read-only checks

Use Terraform CI and the manual Dev Plan to validate configuration and inspect proposed changes. Plan supports core, https-foundation and https-access. It initializes the existing state and does not apply. Apply is manual and requires a fresh plan, strict guard checks and the protected dev-network-apply Environment.

Local checks that do not access GCS:

    terraform -chdir=terraform fmt -check -recursive
    terraform -chdir=terraform init -backend=false -input=false -lockfile=readonly
    terraform -chdir=terraform validate
    python -m unittest discover -s scripts -p 'test_*.py' -v

The backend prefixes are helpdeskcloud/dev, helpdeskcloud/dev-https and helpdeskcloud/dev-https-access in bucket helpdeskcloud-tfstate-511905. A plan with zero requested changes may still report provider drift. Read the guard's drift report and the complete plan before any approved Apply.

## Owner-approved IAP Admin access

The project-level Terraform service account intentionally retains roles/iap.admin. The owner explicitly requested it after previous IAP IAM failures. Do not revoke, reduce or replace it as part of cleanup. The single-user end-user grant remains a distinct roles/iap.httpsResourceAccessor binding in the https-access root, on the exact GKE backend and for mahmoud.hachem23743@gmail.com.

## Deprecated FreeDNS resources

The current hostname is helpdeskcloud.dynv6.net. The older hostname helpdeskcloud.chickenkiller.com remains Terraform-managed and protected with prevent_destroy. Its exact addresses in terraform/https-foundation are:

- google_certificate_manager_dns_authorization.https
- google_certificate_manager_certificate.https
- google_certificate_manager_certificate_map_entry.https

The legacy certificate-map entry and active dynv6 entry both reference google_certificate_manager_certificate_map.https. The current Gateway uses that shared map, but its route and certificate match the dynv6 hostname; it does not depend on the old hostname entry to serve the active host. The old entry still depends on its DNS authorization and certificate.

Eventual decommission requires a separate review confirming no DNS record, Gateway, rollback process or other client uses the old hostname; a plan against the existing https-foundation state; and explicit owner approval. Remove the legacy map entry and certificate/DNS authorization through a sequenced, state-backed change only after verifying the active dynv6 entry and shared map remain. Do not remove prevent_destroy or state records to make an otherwise unsafe plan pass. This cleanup does not delete cloud resources.

## Preserved Apply guard complexity

scripts/dev_infra_guard.py and its extensive tests contain exact drift and recovery checks tied to historical provider readbacks and the prior Apply #12 state. They are retained because they still reject unsafe changes and the current suite covers those invariants. Do not delete incident fixtures unless equivalent rejection tests prove the safety intent remains.
