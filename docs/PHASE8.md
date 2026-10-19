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

`scripts/dev_infra_guard.py` now accepts only this exact four-resource Phase 8 creation batch after the complete Phase 7 inventory exists. It rejects partial batches, changed or deleted existing resources, broader WIF claims, a different subject, and a project-wide repository role. The protected Apply workflow's read-only post-apply check also verifies the new service account, provider, impersonation policy, and repository Writer binding.

Terraform CI runs on a feature PR to `dev` with backend access disabled and no cloud credentials. The remote Dev plan is available only from the trusted `dev` branch through the existing manual Plan workflow and existing infrastructure OIDC identity. After review and merge, a reviewer can dispatch that Plan workflow. No Apply has been run for this change.

The existing `helpdesk-terraform-dev` role grants were not read from Cloud IAM in this branch. Before using the protected Apply workflow, verify that this infrastructure identity can:

- Create and read the new service account (`iam.serviceAccounts.create`, `iam.serviceAccounts.get`).
- Read and set the service account IAM policy for its WIF binding (`iam.serviceAccounts.getIamPolicy`, `iam.serviceAccounts.setIamPolicy`).
- Create/read/update the new provider under the existing pool (`iam.workloadIdentityPoolProviders.create`, `.get`, `.update`). Pool creation permission is not needed.
- Read and set IAM policy on the existing Artifact Registry repository (`artifactregistry.repositories.getIamPolicy`, `artifactregistry.repositories.setIamPolicy`).

Grant only missing permissions to the infrastructure Terraform identity through a separately reviewed IAM change; do not grant the new publisher infrastructure privileges. Google documents these permissions in its [IAM role reference](https://docs.cloud.google.com/iam/docs/roles-permissions/iam), [WIF provider create API](https://docs.cloud.google.com/iam/docs/reference/rest/v1/projects.locations.workloadIdentityPools.providers/create), and [Artifact Registry audit permission reference](https://docs.cloud.google.com/artifact-registry/docs/audit-logging). Also confirm the target provider ID is not already present. If it exists outside Terraform state, import and review it rather than attempting to recreate it.

The App publisher remains disabled until its dedicated provider/service account and scoped grant are reviewed, the protected Environment has required reviewers and a `dev` branch policy, and `DEV_SUPPORTING_IMAGES_PUBLISH_ENABLED` is explicitly set to `true`. Image publication remains a separate manual workflow dispatch and approval.
