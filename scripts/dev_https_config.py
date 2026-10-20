#!/usr/bin/env python3
"""Read and validate stable, nonsensitive HTTPS Dev configuration."""

import re
import sys
from pathlib import Path


HOSTNAME_LINE = re.compile(r'^\s*hostname\s*=\s*"([^"]+)"\s*(?:#.*)?$')
HOSTNAME_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def load_hostname(path):
    matches = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = HOSTNAME_LINE.fullmatch(line)
        if match:
            matches.append(match.group(1))
        elif re.match(r"^\s*hostname\s*=", line):
            raise ValueError("Dev hostname must be one plain quoted hostname assignment")
    if len(matches) != 1:
        raise ValueError("Dev HTTPS variable file must contain exactly one hostname")
    hostname = matches[0]
    labels = hostname.split(".")
    if (len(hostname) > 253 or len(labels) < 2
            or any(not HOSTNAME_LABEL.fullmatch(label) for label in labels)
            or re.fullmatch(r"[0-9.]+", hostname)):
        raise ValueError("Dev HTTPS hostname must be one lower-case DNS hostname")
    return hostname


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "hostname":
        raise SystemExit("Usage: dev_https_config.py hostname TFVARS_FILE")
    try:
        print(load_hostname(sys.argv[2]))
    except (OSError, ValueError) as error:
        print(f"HTTPS configuration is not ready: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
