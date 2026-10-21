"""Render only resource addresses and actions from a Terraform plan JSON file."""

import argparse
import json
from pathlib import Path


def summarize(plan, root):
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise ValueError("Terraform plan has no resource change list")
    entries = []
    for item in changes:
        if item.get("mode", "managed") != "managed":
            continue
        address = item.get("address")
        actions = item.get("change", {}).get("actions")
        if not isinstance(address, str) or not isinstance(actions, list):
            raise ValueError("Terraform plan contains a malformed resource change")
        action = ", ".join(actions) if actions else "unknown"
        entries.append((address, action))
    counts = {key: 0 for key in ("create", "update", "delete", "no-op", "other")}
    for _, action in entries:
        if action in counts:
            counts[action] += 1
        elif action == "delete, create" or action == "create, delete":
            counts["delete"] += 1
            counts["create"] += 1
        else:
            counts["other"] += 1
    lines = [
        "## Terraform plan summary",
        "",
        f"- Root: `{root}`",
        f"- Resource changes: {len(entries)}",
        f"- Actions: {counts['create']} create, {counts['update']} update, {counts['delete']} delete, {counts['no-op']} no-op, {counts['other']} other",
        "",
    ]
    if entries:
        lines.extend(("| Actions | Resource address |", "|---|---|"))
        lines.extend(f"| {action} | `{address}` |" for address, action in sorted(entries))
    else:
        lines.append("No managed resource actions were proposed.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan_file", type=Path)
    parser.add_argument("root")
    parser.add_argument("--summary-file", type=Path)
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.plan_file.read_text(encoding="utf-8"))
        output = summarize(plan, args.root)
        if args.summary_file:
            with args.summary_file.open("a", encoding="utf-8") as stream:
                stream.write(output)
        print(output, end="")
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
