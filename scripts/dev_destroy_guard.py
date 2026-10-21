"""Fail-closed policy checks for the future Dev infrastructure destroy workflow.

This module has no cloud client and never executes Terraform. It validates
operator input, the selected state backend, protected Environment metadata,
backup evidence metadata, a state-backed inventory preview, and a sanitized
Terraform destroy plan inventory.
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
    # A full root destroy must stop while these deletion protections remain.
    # Removing one requires a separate, reviewed recovery decision and code change.
    "core": {
        "google_sql_database_instance.dev_postgres[0]",
        "google_sql_database.dev_helpdesk[0]",
    },
    "https-foundation": set(FOUNDATION),
    "https-access": set(),
}
PROTECTION_METHODS = {
    "core": {
        "google_sql_database_instance.dev_postgres[0]": "Cloud SQL API deletion protection",
        "google_sql_database.dev_helpdesk[0]": "prevent_destroy",
    },
    "https-foundation": {
        address: "prevent_destroy" for address in FOUNDATION
    },
    "https-access": {},
}
IDENTITY_FIELDS = (
    "id", "name", "self_link", "project", "region", "zone", "role", "member",
    "service", "backend_service", "hostname", "network", "database", "instance",
    "certificate", "map", "location", "email",
)
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
        require(not PROTECTED_RESOURCES[root],
                "This root contains retained deletion protections; use plan-only inventory preview")
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


def _resource_identity(attributes, address):
    require(isinstance(attributes, dict), f"Resource identity is unavailable for {address}")
    identity = {
        key: attributes[key] for key in IDENTITY_FIELDS
        if key in attributes and isinstance(attributes[key], (str, int, float))
        and not isinstance(attributes[key], bool) and str(attributes[key]).strip()
    }
    require(bool(identity), f"No stable resource identity fields are available for {address}")
    return identity


def _state_resources(state, root):
    require(isinstance(state, dict), "Terraform state is malformed")
    resources = state.get("resources")
    require(isinstance(resources, list), "Terraform state has no resource inventory")
    inventory = RESOURCE_INVENTORY[root]
    found = {}
    for resource in resources:
        require(isinstance(resource, dict), "Terraform state contains a malformed resource")
        if resource.get("mode", "managed") != "managed":
            continue
        resource_type = resource.get("type")
        name = resource.get("name")
        require(isinstance(resource_type, str) and isinstance(name, str),
                "Terraform state contains a resource without a type or name")
        module = resource.get("module", "")
        require(isinstance(module, str), "Terraform state module path is malformed")
        base = f"{module + '.' if module else ''}{resource_type}.{name}"
        instances = resource.get("instances")
        require(isinstance(instances, list), f"Terraform state instances are malformed for {base}")
        for instance in instances:
            require(isinstance(instance, dict), f"Terraform state instance is malformed for {base}")
            index = instance.get("index_key")
            address = base
            if isinstance(index, int) and not isinstance(index, bool):
                address += f"[{index}]"
            elif isinstance(index, str):
                address += f"[{json.dumps(index)}]"
            elif index is not None:
                raise ValueError(f"Unsupported Terraform state instance key for {base}")
            require(address in inventory,
                    f"Terraform state contains an unexpected managed resource address: {address}")
            require(resource_type == inventory[address],
                    f"Terraform state resource type does not match the reviewed address: {address}")
            attributes = instance.get("attributes")
            found[address] = {
                "type": resource_type,
                "identity": _resource_identity(attributes, address),
            }
    require(len(found) == sum(len(resource.get("instances", [])) for resource in resources
                              if isinstance(resource, dict) and resource.get("mode", "managed") == "managed"),
            "Terraform state contains duplicate managed resource addresses")
    return found


def _state_evidence(state, state_generation):
    require(str(state_generation).isdigit(), "Current GCS state object generation is unavailable")
    serial = state.get("serial") if isinstance(state, dict) else None
    lineage = state.get("lineage") if isinstance(state, dict) else None
    require(isinstance(serial, int) and serial >= 0,
            "Terraform state serial is unavailable")
    require(isinstance(lineage, str) and lineage.strip(),
            "Terraform state lineage is unavailable")
    return {
        "object_generation": str(state_generation),
        "serial": serial,
        "lineage": lineage,
    }


def _fingerprint(root, evidence, resources):
    fingerprint_data = {
        "root": root,
        "bucket": STATE_BUCKET,
        "prefix": BACKENDS[root][2],
        "state": evidence,
        "resources": resources,
    }
    encoded = json.dumps(fingerprint_data, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_state_inventory(state, root, state_generation):
    """Create an inventory-only preview for roots with retained destroy protections."""
    require(root in RESOURCE_INVENTORY and PROTECTED_RESOURCES[root],
            "Inventory-only preview is reserved for roots with retained deletion protections")
    resources = _state_resources(state, root)
    evidence = _state_evidence(state, state_generation)
    entries = [
        {
            "address": address,
            "type": item["type"],
            "identity": item["identity"],
            "protection": PROTECTION_METHODS[root].get(address, "none"),
        }
        for address, item in sorted(resources.items())
    ]
    fingerprint = _fingerprint(root, evidence, entries)
    protected_count = sum(item["protection"] != "none" for item in entries)
    summary = [
        "## Terraform state inventory (no destroy plan)",
        "",
        f"- Project: `{PROJECT_ID}`",
        f"- Root: `{root}`",
        f"- State: `gs://{STATE_BUCKET}/{BACKENDS[root][2]}`",
        f"- State object generation: `{evidence['object_generation']}`",
        f"- Terraform lineage and serial: `{evidence['lineage']}` / `{evidence['serial']}`",
        f"- Resources inventoried: {len(entries)}; resources with retained deletion protection: {protected_count}",
        "- Preview type: state inventory only. No destroy actions or dependency ordering were calculated.",
        "- Fingerprint binds resource types, addresses and stable identities to the state object generation, lineage and serial; identity values are not printed.",
        f"- Review fingerprint: `{fingerprint}`",
        "",
        "This inventory fingerprint supports comparison only and cannot authorize a destroy.",
        "| Resource type | Terraform address | Protection |",
        "|---|---|---|",
    ]
    summary.extend(
        f"| `{item['type']}` | `{item['address']}` | "
        f"{item['protection']} |"
        for item in entries
    )
    if not entries:
        summary.append("| — | No managed resources in this state | — |")
    return fingerprint, "\n".join(summary) + "\n"


def validate_destroy_plan(plan, root, mode="destroy", state=None, state_generation=None):
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
    require(isinstance(state, dict), "State evidence is required to fingerprint a destroy plan")
    state_resources = _state_resources(state, root)
    evidence = _state_evidence(state, state_generation)
    entries = []
    for address, change in sorted(by_address.items()):
        detail = change["change"]
        identity = _resource_identity(detail.get("before"), address)
        require(state_resources.get(address) == {"type": change["type"], "identity": identity},
                f"Plan identity does not match the selected Terraform state for {address}")
        entries.append({
            "address": address,
            "type": change["type"],
            "identity": identity,
            "actions": detail["actions"],
        })
    fingerprint = _fingerprint(root, evidence, entries)
    summary = [
        "## Reviewed destroy plan inventory",
        "",
        f"- Project: `{PROJECT_ID}`",
        f"- Root: `{root}`",
        f"- State: `gs://{STATE_BUCKET}/{BACKENDS[root][2]}`",
        f"- State object generation: `{evidence['object_generation']}`",
        f"- Terraform lineage and serial: `{evidence['lineage']}` / `{evidence['serial']}`",
        f"- Planned deletes: {len(by_address)}",
        "- Fingerprint binds resource types, addresses, stable identities and actions to state object generation, lineage and serial; identity values are not printed.",
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
    inspect.add_argument("--state-file", required=True, type=Path)
    inspect.add_argument("--state-generation", required=True)
    inspect.add_argument("--summary-file", type=Path)
    inspect.add_argument("--output-file", type=Path)

    inventory = commands.add_parser("inventory")
    inventory.add_argument("--root", required=True)
    inventory.add_argument("--state-file", required=True, type=Path)
    inventory.add_argument("--state-generation", required=True)
    inventory.add_argument("--summary-file", type=Path)
    inventory.add_argument("--output-file", type=Path)

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
                json.loads(args.plan_file.read_text(encoding="utf-8")), args.root, args.mode,
                json.loads(args.state_file.read_text(encoding="utf-8")), args.state_generation,
            )
            write_summary(args.summary_file, summary)
            if args.output_file:
                with args.output_file.open("a", encoding="utf-8") as stream:
                    stream.write(f"fingerprint={fingerprint}\n")
            print(f"Destroy plan fingerprint: {fingerprint}")
        elif args.command == "inventory":
            fingerprint, summary = validate_state_inventory(
                json.loads(args.state_file.read_text(encoding="utf-8")), args.root,
                args.state_generation,
            )
            write_summary(args.summary_file, summary)
            if args.output_file:
                with args.output_file.open("a", encoding="utf-8") as stream:
                    stream.write(f"fingerprint={fingerprint}\n")
            print(f"State inventory fingerprint: {fingerprint}")
        return 0
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
