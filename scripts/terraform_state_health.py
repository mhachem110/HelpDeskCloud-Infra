"""Offline checks for the Terraform state bucket's recovery-readiness metadata."""

import argparse
import json
import sys
from pathlib import Path


PROJECT_ID = "helpdeskcloud-capstone-511905"
STATE_BUCKET = "helpdeskcloud-tfstate-511905"
ROOTS = {
    "core": ("terraform/environments/dev.gcs.tfbackend", "helpdeskcloud/dev"),
    "https-foundation": (
        "terraform/https-foundation/environments/dev.gcs.tfbackend",
        "helpdeskcloud/dev-https",
    ),
    "https-access": (
        "terraform/https-access/environments/dev.gcs.tfbackend",
        "helpdeskcloud/dev-https-access",
    ),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _backend_values(path):
    values = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def validate_backend_files(repository_root):
    root = Path(repository_root)
    for name, (relative_path, expected_prefix) in ROOTS.items():
        path = root / relative_path
        values = _backend_values(path)
        require(values.get("bucket") == STATE_BUCKET,
                f"{name} backend uses an unexpected GCS bucket")
        require(values.get("prefix") == expected_prefix,
                f"{name} backend uses an unexpected GCS prefix")
    return True


def _lifecycle_targets_state(rule, prefix):
    action = rule.get("action", {})
    if action.get("type") != "Delete":
        return False
    condition = rule.get("condition", {})
    matches_prefix = condition.get("matchesPrefix")
    if not matches_prefix:
        return True
    return any(prefix.startswith(candidate) or candidate.startswith(prefix)
               for candidate in matches_prefix)


def validate_bucket_metadata(bucket, versions_by_root, current_objects_by_root=None):
    require(isinstance(bucket, dict) and bucket.get("name") == STATE_BUCKET,
            "State bucket identity is missing or incorrect")
    require(bucket.get("versioning", {}).get("enabled") is True,
            "GCS object versioning is not enabled for Terraform state recovery")
    iam = bucket.get("iamConfiguration", {})
    require(iam.get("uniformBucketLevelAccess", {}).get("enabled") is True,
            "Uniform bucket-level access is not enabled for Terraform state")
    require(iam.get("publicAccessPrevention") in {"enforced", "inherited"},
            "Public access prevention is not enabled for Terraform state")

    lifecycle_rules = bucket.get("lifecycle", {}).get("rule", [])
    unsafe_rules = []
    for rule in lifecycle_rules:
        for root, (_, prefix) in ROOTS.items():
            if _lifecycle_targets_state(rule, prefix):
                unsafe_rules.append((root, rule))
    require(not unsafe_rules,
            "A bucket lifecycle Delete rule may remove Terraform state or its version history")

    root_lines = []
    for root, (_, prefix) in ROOTS.items():
        expected_name = f"{prefix}/default.tfstate"
        objects = versions_by_root.get(root)
        require(isinstance(objects, list), f"State version metadata is missing for {root}")
        names = {item.get("name") for item in objects if isinstance(item, dict)}
        require(names == {expected_name},
                f"State metadata for {root} contains a missing or unexpected object name")
        generations = {
            str(item.get("generation")) for item in objects
            if isinstance(item, dict) and str(item.get("generation", "")).isdigit()
        }
        require(bool(generations),
                f"No state object generation is available for {root}")
        current_objects = current_objects_by_root or {}
        current = current_objects.get(root)
        require(isinstance(current, dict) and current.get("name") == expected_name
                and str(current.get("generation", "")).isdigit(),
                f"Current state object metadata is unreadable or unexpected for {root}")
        require(str(current["generation"]) in generations,
                f"Current state generation is missing from the version listing for {root}")
        history = ("new state; no recovery history is available yet" if len(generations) == 1
                   else f"established state; {len(generations)} generations provide recovery history")
        root_lines.append(
            f"- `{root}`: {history}; current generation {current['generation']} metadata readable; "
            "state contents not read."
        )

    retention = bucket.get("retentionPolicy")
    retention_text = (f"configured for {retention.get('retentionPeriod')} seconds"
                      if isinstance(retention, dict) and retention.get("retentionPeriod")
                      else "not configured; object versioning and backups remain the recovery controls")
    lifecycle_text = f"{len(lifecycle_rules)} lifecycle rule(s), none delete a configured state prefix"
    lines = [
        "## Terraform state recovery readiness",
        "",
        f"- Bucket: `gs://{STATE_BUCKET}`",
        "- Object versioning: enabled",
        f"- Retention policy: {retention_text}",
        f"- Lifecycle: {lifecycle_text}",
        "- Terraform initializer read access: the existing short-lived identity described the bucket and each exact state object, then listed its versions; no IAM was changed.",
        *root_lines,
        "",
        "Only object metadata was listed. No Terraform state contents were downloaded or uploaded.",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    config = commands.add_parser("check-backends")
    config.add_argument("--repository-root", required=True, type=Path)
    inspect = commands.add_parser("inspect")
    for argument in ("bucket-file", "versions-dir"):
        inspect.add_argument(f"--{argument}", required=True, type=Path)
    inspect.add_argument("--summary-file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "check-backends":
            validate_backend_files(args.repository_root)
            print("All three Dev backend bucket and prefix definitions match the reviewed inventory.")
            return 0
        bucket = json.loads(args.bucket_file.read_text(encoding="utf-8"))
        versions = {
            root: json.loads((args.versions_dir / f"{root}.json").read_text(encoding="utf-8"))
            for root in ROOTS
        }
        current_objects = {
            root: json.loads((args.versions_dir / f"{root}-current.json").read_text(encoding="utf-8"))
            for root in ROOTS
        }
        report = validate_bucket_metadata(bucket, versions, current_objects)
        if args.summary_file:
            with args.summary_file.open("a", encoding="utf-8") as stream:
                stream.write(report)
        print(report, end="")
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
