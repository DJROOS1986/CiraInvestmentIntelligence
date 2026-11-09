#!/usr/bin/env python3
"""CIRA Phase 5.5 explicit promotion/recovery dispatcher.

This wrapper never automatically promotes or recovers.
"""

import argparse
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent

PROMOTION = HERE / "26-CIRA-Safe-Promotion.py"
RECOVERY = HERE / "28-CIRA-Recovery-Candidate.py"


def main():
    parser = argparse.ArgumentParser(
        description="CIRA explicit promotion/recovery dispatcher"
    )

    parser.add_argument("--status", action="store_true")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--confirm-local-recovery", action="store_true")

    parser.add_argument("--stage", type=pathlib.Path)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--confirm-local-replacement", action="store_true")

    args = parser.parse_args()

    if args.status:
        if any((
            args.recover,
            args.confirm_local_recovery,
            args.stage is not None,
            args.promote,
            args.confirm_local_replacement
        )):
            parser.error("--status cannot be combined with other operations")

        command = [
            sys.executable,
            str(RECOVERY),
            "--root",
            str(ROOT),
            "--recovery-status"
        ]

    elif args.recover:
        if not args.confirm_local_recovery:
            parser.error("Recovery requires --confirm-local-recovery")

        if any((
            args.stage is not None,
            args.promote,
            args.confirm_local_replacement
        )):
            parser.error("Recovery cannot be combined with promotion")

        command = [
            sys.executable,
            str(RECOVERY),
            "--root",
            str(ROOT),
            "--recover",
            "--confirm-local-recovery"
        ]

    elif args.promote:
        if args.stage is None:
            parser.error("Promotion requires --stage")

        if not args.confirm_local_replacement:
            parser.error("Promotion requires --confirm-local-replacement")

        if args.confirm_local_recovery:
            parser.error("Promotion cannot include recovery confirmation")

        command = [
            sys.executable,
            str(PROMOTION),
            "--stage",
            str(args.stage.resolve()),
            "--promote",
            "--confirm-local-replacement"
        ]

    else:
        parser.error(
            "Choose --status, --recover, or --promote explicitly"
        )

    return subprocess.call(command, cwd=str(ROOT))


if __name__ == "__main__":
    sys.exit(main())