# Phase 8 — supporting-image publisher IAM

## Scope

This Terraform change prepares the Google Cloud identity used by the separate `HelpDeskCloud-App` supporting-image publisher. It adds one Dev service account, one GitHub OIDC provider under the existing `helpdesk-github` Workload Identity Pool, an exact-subject impersonation binding, and an Artifact Registry Writer grant on only `us-east1/helpdeskcloud-dev-images`.

It does not create a pool, change `github-infra-dev`, change the existing Terraform identities, publish images, enable App repository variables, run the database migration, or create Stage or Production resources. The existing `terraform-dev-plan.yml` and protected `terraform-dev-apply.yml` continue to use the infrastructure-only provider and service account.

## GitHub trust verification

The App repository's **Settings → Actions → OIDC** page was inspected on 2026-10-19. It shows the default subject template, immutable subject claims enabled, and this immutable prefix:

```text
repo:mhachem110@150286776/HelpDeskCloud-App@1423008128
```

The publisher job in `.github/workflows/supporting-images-ci.yml` uses the protected `dev-supporting-images-publish` GitHub Environment. GitHub's documented environment subject format therefore yields this exact subject, which Terraform binds to the new service account:

```text
repo:mhachem110@150286776/HelpDeskCloud-App@1423008128:environment:dev-supporting-images-publish
```

The provider independently requires the verified owner and repository IDs, repository name, `refs/heads/dev`, that exact Environment, and the exact `supporting-images-ci.yml@refs/heads/dev` workflow reference. The binding does not use a repository-wide principal set. Recheck the App OIDC settings and workflow ref if either is renamed or customized before applying.

References: [GitHub OIDC subject claims](https://docs.github.com/en/actions/reference/security/oidc) and [Google Cloud Workload Identity Federation for deployment pipelines](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines).

## Service-account ID limit

Google service-account IDs are limited to 30 characters. The requested `helpdesk-app-support-image-publisher-dev` is 40 characters and cannot be used as the email local part. Terraform uses the valid ID `helpdesk-app-support-pub-dev` (28 characters) and retains the requested full value as the service account display name. Its email is:

```text
helpdesk-app-support-pub-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com
```

The App publisher workflow must use this valid email before an approved publication run. Its current workflow references the overlength local part; that integration update must be merged before publication.

Reference: [Create service accounts](https://cloud.google.com/iam/docs/service-accounts-create).

## Access boundaries

The publisher service account receives only:

- `roles/iam.workloadIdentityUser` on itself, granted to the exact verified Environment subject.
- `roles/artifactregistry.writer` on the existing `helpdeskcloud-dev-images` repository in `us-east1`.

It receives no project-wide Artifact Registry role, Terraform state access, Cloud SQL permission, Secret Manager access, or GKE access. Artifact Registry tag immutability remains configured by the existing repository resource. The App workflow remains responsible for CI scans, provenance verification, manual dispatch, Environment approval, unique non-overwriting tags, and digest capture.

## Plan and apply review

`scripts/dev_infra_guard.py` accepts this exact four-resource Phase 8 creation batch after the complete Phase 7 inventory exists. It rejects partial batches, changed or deleted existing resources, broader WIF claims, a different subject, and a project-wide repository role. The protected Apply workflow's read-only post-apply check also verifies the new service account, provider, impersonation policy, and repository Writer binding.

### Apply #21 partial completion and recovery

Terraform Dev Apply #21 created the publisher service account, its exact-subject Workload Identity User binding, and the repository-scoped Artifact Registry Writer binding. Creation of `google_iam_workload_identity_pool_provider.dev_app_support_images[0]` failed because the Terraform identity lacks `iam.workloadIdentityPoolProviders.create` on the existing `helpdesk-github` pool. No permission change or manual provider creation is included in this recovery.

The recovery guard accepts only a remote prior state containing the complete Phase 7 inventory and exactly these three Phase 8 resources, each with the approved identity, subject, role, project, location, and repository values:

- `google_service_account.dev_app_support_image_publisher[0]`
- `google_service_account_iam_member.dev_app_support_images_wif[0]`
- `google_artifact_registry_repository_iam_member.dev_app_support_images_writer[0]`

The pinned Google provider reads the IAM resource's `repository` value back as the canonical path `projects/helpdeskcloud-capstone-511905/locations/us-east1/repositories/helpdeskcloud-dev-images`, even though Terraform configuration references the repository ID `helpdeskcloud-dev-images`. This behavior is implemented in the provider's [v7.8.0 IAM updater](https://github.com/hashicorp/terraform-provider-google/blob/v7.8.0/google/services/artifactregistry/iam_artifact_registry_repository.go). The guard accepts those two explicit representations only. It separately pins the project, `us-east1` location, `roles/artifactregistry.writer`, and publisher service-account member; another project, region, repository, role, or identity remains rejected.

The only allowed creation is `google_iam_workload_identity_pool_provider.dev_app_support_images[0]`. Other partial inventories, another creation, any update, replacement, or deletion remain blocked. The guard checks the three existing resources directly in Terraform's prior state as well as checking all planned values.

After Apply #21, the read-only Terraform Dev Plan reported exactly one resource to add, no changes, and no destroys. It also reported an etag-only readback for the existing GKE image-pull grant because the new Writer member changed the repository IAM policy etag. The guard permits only a different, non-empty etag when the existing reader's project, location, repository, role, member, and all other state fields remain identical. Other repository IAM drift remains blocked.

Terraform CI runs on a feature PR to `dev` with backend access disabled and no cloud credentials. The remote Dev plan is available only from the trusted `dev` branch through the existing manual Plan workflow and existing infrastructure OIDC identity. After review and merge, a reviewer can dispatch that Plan workflow. The recovery PR changes only the plan guard, tests, and this runbook; it does not run Apply or alter the remote state.

The existing `helpdesk-terraform-dev` role grants were not read from Cloud IAM in this branch. Before using the protected Apply workflow, verify that this infrastructure identity can:

- Create and read the new service account (`iam.serviceAccounts.create`, `iam.serviceAccounts.get`).
- Read and set the service account IAM policy for its WIF binding (`iam.serviceAccounts.getIamPolicy`, `iam.serviceAccounts.setIamPolicy`).
- Create/read/update the new provider under the existing pool (`iam.workloadIdentityPoolProviders.create`, `.get`, `.update`). Pool creation permission is not needed.
- Read and set IAM policy on the existing Artifact Registry repository (`artifactregistry.repositories.getIamPolicy`, `artifactregistry.repositories.setIamPolicy`).

Apply #21 failed at that time because the Terraform identity lacked `iam.workloadIdentityPoolProviders.create` on the existing pool. Apply #22 later created the provider successfully. That successful create confirms the identity had effective create access during Apply #22; the workflow logs do not establish which IAM change enabled it. Keep the Terraform identity's pool permissions narrowly scoped. Google documents these permissions in its [IAM role reference](https://docs.cloud.google.com/iam/docs/roles-permissions/iam), [WIF provider create API](https://docs.cloud.google.com/iam/docs/reference/rest/v1/projects.locations.workloadIdentityPools.providers/create), and [Artifact Registry audit permission reference](https://docs.cloud.google.com/artifact-registry/docs/audit-logging). The Apply #21 recovery guard required the provider to be absent from prior state before allowing its creation.

### Apply #22 post-apply verification

Apply #22 created the remaining supporting-image provider successfully (`1 added, 0 changed, 0 destroyed`). The job then failed before post-apply evidence validation because the guard CLI still enforced its earlier Phase 7 argument count, while the workflow supplied the three additional Phase 8 evidence files and `verify_deployment` already expected all 25 inputs. The CLI arity and usage now match the workflow, with a regression test for the 25-file invocation and the obsolete count. Run a fresh protected Dev operation after this fix to validate the deployed state; the failed Apply #22 has already committed its provider creation to Terraform state.

The App publisher remains disabled until its dedicated provider/service account and scoped grant are reviewed, the protected Environment has required reviewers and a `dev` branch policy, and `DEV_SUPPORTING_IMAGES_PUBLISH_ENABLED` is explicitly set to `true`. Image publication remains a separate manual workflow dispatch and approval.

### Apply #23 read-only plan and provider audience readback

Apply #23 stopped in its read-only **Show Dev plan** job. Terraform reported no requested changes, and the protected **Approved Dev operation** job was skipped, so this run did not modify cloud resources. The drift diagnostic identified only `google_iam_workload_identity_pool_provider.dev_app_support_images[0]` at `oidc[0].allowed_audiences`; it intentionally did not print the before/after values. The run output therefore identifies the field but does not establish which unset representation Terraform observed.

The guard now permits a provider readback update only when `allowed_audiences` changes between the exact unset representations `missing`, `null`, or `[]`. Both snapshots must retain the exact Dev project, existing `helpdesk-github` pool, `github-app-support-images-dev` provider, enabled state, verified attribute mapping and condition, GitHub Actions issuer, and provider ID. After removing only that one field, the complete snapshots must be identical. A non-empty audience, a change to another provider field, any requested update, or any unrelated drift remains blocked. The diagnostic reports only the two audience representation classes and whether the provider identity matches; audience values stay withheld.

The guard tests model these representation pairs and reject non-empty audiences, altered issuer/trust/provider identity, and other field changes. They also read `.github/workflows/terraform-dev-apply.yml` and assert that its ordered evidence-file arguments match the guard's 25-input interface. That contract test is intended to catch workflow/guard argument-count drift in CI before merge. A fresh Dev Plan is still required to confirm that the observed readback fits the narrow allowance and that the plan contains no requested changes; this change does not run Apply.

### Provider identity readback diagnostics

The latest approved-operation **Show Dev plan** stage (Apply workflow run #25) reported **no Terraform changes** and only the already documented `oidc[0].allowed_audiences` drift (`null` to `[]`). The diagnostic classified both provider identities as unexpected but withheld their values. The provider's successful create in Apply #22 logged the canonical resource ID with the project **ID** (`projects/helpdeskcloud-capstone-511905/...`), so the readback guard continues to require that exact ID path; a project-number path is not accepted.

The guard compared `attribute_condition` byte-for-byte with a compact expected string, while the reviewed provider configuration and Terraform plan render it as a multiline heredoc. That formatting-only difference can make both otherwise identical provider snapshots fail the aggregate identity check and block the narrowly permitted audience normalization. The comparison now collapses whitespace only outside CEL string literals. Repository name, immutable repository and owner IDs, branch, GitHub Environment, workflow reference, issuer, attribute mapping, provider IDs, and the project-ID resource path remain exact. Whitespace inside any quoted trust value is preserved and rejected if changed.

The drift diagnostic now reports each provider identity comparison as `expected` or `unexpected` without printing provider values. Regression tests cover the multiline Terraform CEL readback paired with `null` to `[]` audiences, preserve the project-ID canonical resource path, and reject changed trust literals, issuer, mapping, and a project-number provider path. The next read-only Dev Plan should report `attribute_condition=expected` for both snapshots, accept only the audience representation drift, and return a no-change decision. No cloud resource or IAM binding was modified by this guard change.
