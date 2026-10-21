"""Fail-closed policy checks for the future Dev infrastructure destroy workflow.

This module has no cloud client and never executes Terraform. It validates
operator input, the selected state backend, protected Environment metadata,
backup evidence metadata, and a sanitized Terraform plan inventory.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from dev_https_guard import ACCESS, FOUNDATION
from dev_infra_guard import EXPECTED


REPOSITORY = "mhachem110/HelpDeskCloud-Infra"
BRANCH = "refs/heads/dev"
PROJECT_ID = "helpdeskcloud-capstone-511905"
ENVIRONMENT = "dev-infra-destroy"
STATE_BUCKET = "helpdeskcloud-tfstate-511905"
BACKENDS = {
    "core": ("terraform", "environments/dev.gcs.tfbackend", "helpdeskcloud/dev"),
    "https-foundation": (
        "terraform/https-foundation",
        "environments/dev.gcs.tfbackend",
        "helpdeskcloud/dev-https",
    ),
    "https-access": (
        "terraform/https-access",
        "environments/dev.gcs.tfbackend",
        "helpdeskcloud/dev-https-access",
    ),
}
RESOURCE_INVENTORY = {
    "core": EXPECTED,
    "https-foundation": FOUNDATION,
    "https-access": ACCESS,
}
PROTECTED_RESOURCES = {
    # A full root destroy must stop while these lifecycle protections remain.
    # Removing one requires a separate, reviewed recovery decision and code change.
    "core": {
        "google_sql_database_instance.dev_postgres[0]",
        "google_sql_database.dev_helpdesk[0]",
    },
    "https-foundation": set(FOUNDATION),
    "https-access": set(),
}
CONFIRMATION_PREFIX = "DESTROY dev helpdeskcloud-capstone-511905"
SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_selection(*, mode, repository, ref, project_id, root,
                       confirmation="", opt_in="false", reviewed_fingerprint=""):
    """Validate exact identity and require separate gates for destructive mode."""
    require(mode in {"plan-only", "destroy"}, "Choose plan-only or destroy mode")
    require(repository == REPOSITORY, "Unexpected repository")
    require(ref == BRANCH, "Destroy operations are limited to the protected dev branch")
    require(project_id == PROJECT_ID, "Unexpected GCP project ID")
    require(root in BACKENDS, "Select exactly one supported Terraform root")
    if mode == "destroy":
        expected_confirmation = f"{CONFIRMATION_PREFIX} {root}"
        require(confirmation == expected_confirmation,
                "Typed destroy confirmation does not match the selected environment, project, and root")
        require(opt_in == "true", "DEV_DESTROY_ENABLED is not enabled")
        require(bool(SHA256.fullmatch(reviewed_fingerprint)),
                "A SHA-256 fingerprint from a separate plan-only review is required")
    return BACKENDS[root]


def validate_backend(root, bucket, prefix):
    require(root in BACKENDS, "Unknown Terraform root")
    require(bucket == STATE_BUCKET, "Unexpected Terraform state bucket")
    require(prefix == BACKENDS[root][2], "Unexpected Terraform state prefix")
    return True


def validate_environment(environment, branch_policies):
    """Require a pre-existing dev-only Environment with independent review."""
    require(isinstance(environment, dict) and environment.get("name") == ENVIRONMENT,
            "Required dev-infra-destroy Environment does not exist")
    policy = environment.get("deployment_branch_policy")
    require(isinstance(policy, dict) and policy.get("custom_branch_policies") is True,
            "Destroy Environment must restrict deployments to explicitly configured branches")
    rules = environment.get("protection_rules")
    reviewers = [rule for rule in rules or []
                 if isinstance(rule, dict) and rule.get("type") == "required_reviewers"]
    require(len(reviewers) == 1, "Destroy Environment must have one required-reviewer rule")
    reviewer_rule = reviewers[0]
    configured_reviewers = reviewer_rule.get("reviewers")
    require(isinstance(configured_reviewers, list) and len(configured_reviewers) > 0
            and all(isinstance(item, dict) and item.get("type") in {"User", "Team"}
                    and isinstance(item.get("reviewer"), dict)
                    and isinstance(item["reviewer"].get("id"), int)
                    for item in configured_reviewers),
            "Destroy Environment must name an authorized reviewer")
    require(reviewer_rule.get("prevent_self_review") is True,
            "Destroy Environment must prevent the workflow requester from approving their own run")
    require(isinstance(branch_policies, dict)
            and branch_policies.get("total_count") == 1
            and len(branch_policies.get("branch_policies", [])) == 1
            and branch_policies["branch_policies"][0].get("name") == "dev",
            "Destroy Environment must allow only the dev branch")
    return True


def validate_backup_evidence(*, uri, confirmation, expected_bucket, expected_state_generation,
                             root, metadata):
    """Check metadata for a separately created and restore-tested backup manifest."""
    validate_backup_uri(uri=uri, expected_bucket=expected_bucket, root=root)
    require(isinstance(metadata, dict), "Backup manifest metadata is unavailable")
    custom = metadata.get("metadata")
    require(isinstance(custom, dict), "Backup manifest requires verified custom metadata")
    generation = str(metadata.get("generation", ""))
    size = metadata.get("size")
    crc32c = metadata.get("crc32c")
    require(generation.isdigit() and str(size).isdigit() and int(size) > 0
            and isinstance(crc32c, str) and bool(crc32c.strip()),
            "Backup manifest object metadata is incomplete")
    require(custom.get("project_id") == PROJECT_ID and custom.get("terraform_root") == root,
            "Backup manifest is for a different project or Terraform root")
    manifest_state_generation = custom.get("terraform_state_generation")
    require(isinstance(manifest_state_generation, str) and manifest_state_generation.isdigit(),
            "Backup manifest does not identify a Terraform state generation")
    require(manifest_state_generation == str(expected_state_generation),
            "Backup manifest does not match the current selected state generation")
    recovery_test_id = custom.get("recovery_test_id")
    require(isinstance(recovery_test_id, str) and recovery_test_id.strip(),
            "Backup manifest does not identify a successful recovery test")
    if root == "core":
        cloud_sql_backup_id = custom.get("cloud_sql_backup_id")
        require(isinstance(cloud_sql_backup_id, str) and cloud_sql_backup_id.strip(),
                "Core teardown requires a separate Cloud SQL backup reference")
    require(confirmation == f"BACKUP VERIFIED {root} generation {generation}",
            "Type the exact backup verification confirmation for this manifest generation")
    return generation


def validate_backup_uri(*, uri, expected_bucket, root):
    """Validate a backup object path before making any cloud metadata request."""
    require(root in BACKENDS, "Unknown Terraform root")
    require(isinstance(expected_bucket, str) and expected_bucket.strip(),
            "DEV_DESTROY_BACKUP_BUCKET must be configured separately")
    require(expected_bucket != STATE_BUCKET and "/" not in expected_bucket,
            "Recovery manifests must use a separate GCS bucket from Terraform state")
    prefix = f"gs://{expected_bucket}/dr-recovery/{PROJECT_ID}/{root}/"
    require(isinstance(uri, str) and uri.startswith(prefix) and uri.endswith(".json"),
            "Backup manifest must be in the configured root-specific recovery prefix")
    require(".." not in uri.split("/"), "Backup manifest path must stay inside its root-specific prefix")
    return True


def _resource_blocks(source):
    """Yield resource blocks, ending each block at the next top-level resource."""
    starts = list(re.finditer(r'(?m)^\s*resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', source))
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(source)
        yield f"{match.group(1)}.{match.group(2)}", source[match.end():end]


def validate_protection_configuration(root, terraform_root):
    """Ensure current data/certificate deletion guards remain present in source."""
    require(root in BACKENDS, "Unknown Terraform root")
    required = PROTECTED_RESOURCES[root]
    if not required:
        return True
    paths = list(Path(terraform_root).rglob("*.tf"))
    blocks = {}
    for path in paths:
        for address, body in _resource_blocks(path.read_text(encoding="utf-8")):
            blocks[address] = body
    for address in required:
        body = blocks.get(address.rsplit("[", 1)[0])
        require(body is not None, f"Protected resource declaration is missing: {address}")
        if address == "google_sql_database_instance.dev_postgres[0]":
            require(re.search(r"\bdeletion_protection\s*=\s*true\b", body),
                    "Cloud SQL deletion_protection must remain enabled")
            require(re.search(r"\bdeletion_protection_enabled\s*=\s*true\b", body),
                    "Cloud SQL settings deletion protection must remain enabled")
        else:
            lifecycle = re.search(r"lifecycle\s*\{([^}]*)\}", body, re.DOTALL)
            require(lifecycle is not None
                    and re.search(r"\bprevent_destroy\s*=\s*true\b", lifecycle.group(1)),
                    f"Deletion protection must remain enabled for {address}")
    return True


def _flatten(module):
    resources = list(module.get("resources", []))
    for child in module.get("child_modules", []):
        resources.extend(_flatten(child))
    return resources


def validate_destroy_plan(plan, root, mode="destroy"):
    """Allow only known, one-way deletes; reject replacements and protected data."""
    require(root in RESOURCE_INVENTORY, "Unknown Terraform root")
    require(mode in {"plan-only", "destroy"}, "Unknown destroy-plan mode")
    changes = plan.get("resource_changes")
    require(isinstance(changes, list), "Terraform plan has no resource change inventory")
    require(all(isinstance(change, dict) for change in changes),
            "Terraform plan contains a malformed resource change")
    managed = [change for change in changes if change.get("mode", "managed") == "managed"]
    by_address = {change.get("address"): change for change in managed}
    require(None not in by_address and len(by_address) == len(managed),
            "Terraform plan contains a missing or duplicate resource address")
    allowed = RESOURCE_INVENTORY[root]
    require(set(by_address) <= set(allowed), "Terraform plan contains an unexpected resource address")
    require(bool(by_address), "Destroy plan contains no resources to review")
    for address, change in by_address.items():
        require(change.get("type") == allowed[address],
                f"Resource type does not match the reviewed address: {address}")
        detail = change.get("change")
        require(isinstance(detail, dict), f"Terraform plan change is malformed for {address}")
        actions = detail.get("actions")
        require(actions == ["delete"],
                f"Only a one-way delete is allowed for {address}; replacements and updates are rejected")
        if mode == "destroy":
            require(address not in PROTECTED_RESOURCES[root],
                    f"Protected data or certificate resource cannot be destroyed by this workflow: {address}")
    fingerprint_data = {
        "root": root,
        "bucket": STATE_BUCKET,
        "prefix": BACKENDS[root][2],
        "resources": sorted((address, by_address[address].get("change", {}).get("actions"))
                             for address in by_address),
    }
    encoded = json.dumps(fingerprint_data, separators=(",", ":"), sort_keys=True).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()
    summary = [
        "## Reviewed destroy plan inventory",
        "",
        f"- Project: `{PROJECT_ID}`",
        f"- Root: `{root}`",
        f"- State: `gs://{STATE_BUCKET}/{BACKENDS[root][2]}`",
        f"- Planned deletes: {len(by_address)}",
        f"- Review fingerprint: `{fingerprint}`",
        "",
        "| Action | Terraform address |",
        "|---|---|",
    ]
    summary.extend(
        f"| delete{' (protected; no execution)' if address in PROTECTED_RESOURCES[root] else ''} | `{address}` |"
        for address in sorted(by_address)
    )
    return fingerprint, "\n".join(summary) + "\n"


def write_summary(path, content):
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(content)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    selection = commands.add_parser("selection")
    for name in ("mode", "repository", "ref", "project-id", "root"):
        selection.add_argument(f"--{name}", required=True)
    selection.add_argument("--confirmation", default="")
    selection.add_argument("--opt-in", default="false")
    selection.add_argument("--reviewed-fingerprint", default="")

    backend = commands.add_parser("backend")
    backend.add_argument("--root", required=True)
    backend.add_argument("--file", required=True, type=Path)

    environment = commands.add_parser("environment")
    environment.add_argument("--environment-file", required=True, type=Path)
    environment.add_argument("--branches-file", required=True, type=Path)

    backup = commands.add_parser("backup")
    for name in ("uri", "confirmation", "expected-bucket", "expected-state-generation", "root"):
        backup.add_argument(f"--{name}", required=True)
    backup.add_argument("--metadata-file", required=True, type=Path)

    backup_uri = commands.add_parser("backup-uri")
    for name in ("uri", "expected-bucket", "root"):
        backup_uri.add_argument(f"--{name}", required=True)

    protection = commands.add_parser("protection")
    protection.add_argument("--root", required=True)
    protection.add_argument("--terraform-root", required=True, type=Path)

    inspect = commands.add_parser("inspect-plan")
    inspect.add_argument("--root", required=True)
    inspect.add_argument("--mode", required=True, choices=("plan-only", "destroy"))
    inspect.add_argument("--plan-file", required=True, type=Path)
    inspect.add_argument("--summary-file", type=Path)
    inspect.add_argument("--output-file", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "selection":
            target = validate_selection(
                mode=args.mode, repository=args.repository, ref=args.ref,
                project_id=getattr(args, "project_id"), root=args.root,
                confirmation=args.confirmation, opt_in=args.opt_in,
                reviewed_fingerprint=args.reviewed_fingerprint,
            )
            print(json.dumps({"directory": target[0], "backend": target[1], "prefix": target[2]}))
        elif args.command == "backend":
            values = dict(line.split("=", 1) for line in args.file.read_text(encoding="utf-8").splitlines()
                          if "=" in line)
            bucket = values.get("bucket", "").strip().strip('"')
            prefix = values.get("prefix", "").strip().strip('"')
            validate_backend(args.root, bucket, prefix)
            print("Exact state backend verified.")
        elif args.command == "environment":
            validate_environment(json.loads(args.environment_file.read_text(encoding="utf-8")),
                                 json.loads(args.branches_file.read_text(encoding="utf-8")))
            print("Pre-existing independent reviewer and dev-only Environment verified.")
        elif args.command == "backup":
            generation = validate_backup_evidence(
                uri=args.uri, confirmation=args.confirmation,
                expected_bucket=args.expected_bucket,
                expected_state_generation=args.expected_state_generation, root=args.root,
                metadata=json.loads(args.metadata_file.read_text(encoding="utf-8")),
            )
            print(f"Backup manifest generation {generation} verified; contents were not read.")
        elif args.command == "backup-uri":
            validate_backup_uri(uri=args.uri, expected_bucket=args.expected_bucket, root=args.root)
            print("Backup manifest path is restricted to the selected root's recovery prefix.")
        elif args.command == "protection":
            validate_protection_configuration(args.root, args.terraform_root)
            print("Required data and certificate deletion protections remain enabled.")
        elif args.command == "inspect-plan":
            fingerprint, summary = validate_destroy_plan(
                json.loads(args.plan_file.read_text(encoding="utf-8")), args.root, args.mode
            )
            write_summary(args.summary_file, summary)
            if args.output_file:
                with args.output_file.open("a", encoding="utf-8") as stream:
                    stream.write(f"fingerprint={fingerprint}\n")
            print(f"Destroy plan fingerprint: {fingerprint}")
        return 0
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
