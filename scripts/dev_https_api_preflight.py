"""Report or enforce the one-time Dev HTTPS API bootstrap prerequisite."""

import argparse
import subprocess
import sys


PROJECT = "helpdeskcloud-capstone-511905"
SERVICES = (
    "certificatemanager.googleapis.com",
    "iap.googleapis.com",
)
BOOTSTRAP = (
    "gcloud services enable certificatemanager.googleapis.com iap.googleapis.com "
    f"--project={PROJECT}"
)


def get_states(run=subprocess.run):
    states = {}
    for service in SERVICES:
        result = run(
            ["gcloud", "services", "describe", service, f"--project={PROJECT}", "--format=value(state)"],
            capture_output=True,
            text=True,
            check=False,
        )
        state = result.stdout.strip().upper() if result.returncode == 0 else "UNKNOWN"
        states[service] = state if state in {"ENABLED", "DISABLED"} else "UNKNOWN"
    return states


def main(argv=None, run=subprocess.run, stdout=sys.stdout, stderr=sys.stderr):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-enabled",
        action="store_true",
        help="fail closed unless both APIs were enabled by the project bootstrap identity",
    )
    args = parser.parse_args(argv)
    states = get_states(run)
    for service, state in states.items():
        print(f"{service}: {state}", file=stdout)

    missing = [service for service, state in states.items() if state != "ENABLED"]
    if not missing:
        print("Certificate Manager and IAP APIs are enabled.", file=stdout)
        return 0

    if args.require_enabled:
        print(
            "::error::HTTPS Apply requires the project APIs to be enabled once by a project administrator. "
            f"Run: {BOOTSTRAP}",
            file=stderr,
        )
        return 1

    print(
        "::notice::HTTPS API bootstrap is incomplete. The read-only plan continues; protected Apply will "
        f"stop until a project administrator runs: {BOOTSTRAP}",
        file=stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
