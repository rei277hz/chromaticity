#!/usr/bin/env python3
"""Reject CI selections that could execute proof actions, including indirect deps."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


MANIFEST = Path(__file__).with_name("targets.json")
MAINTENANCE = "//tools/rust-build:distribution"
FORBIDDEN_KINDS = frozenset({"invariant_proof", "invariant_bundle", "verification_group"})
FORBIDDEN_LABELS = frozenset({
    "//libraries/perceptual-grade-core/proofs:color_model",
    "//tools/verification:dependencies",
})


def normalized(label):
    return label.removeprefix("root") if label.startswith("root//") else label


def requested(selection):
    if not isinstance(selection, dict):
        raise ValueError("CI selection must be an object")
    result = []
    for group in ("builds", "tests"):
        labels = selection.get(group)
        if not isinstance(labels, list) or not labels:
            raise ValueError(f"CI {group} selection must be a nonempty list")
        if any(not isinstance(label, str) or not re.fullmatch(r"//[A-Za-z0-9_./+-]*:[A-Za-z0-9_.+=-]+", label)
               for label in labels):
            raise ValueError(f"CI {group} must contain explicit root-cell target labels")
        if len(labels) != len(set(labels)):
            raise ValueError(f"CI {group} selection contains duplicates")
        result.extend(labels)
    return sorted(set(result + [MAINTENANCE]))


def inspect_closure(data, labels):
    if not isinstance(data, dict) or not data:
        raise ValueError("Buck returned no dependency-closure attributes")
    closure = {}
    for label, attributes in data.items():
        if not isinstance(label, str) or not isinstance(attributes, dict):
            raise ValueError("Buck returned malformed dependency-closure attributes")
        kind = attributes.get("buck.type")
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"Buck omitted the rule kind for {label}")
        key = normalized(label)
        if key in closure:
            raise ValueError(f"Buck returned duplicate dependency target {key}")
        closure[key] = kind
    missing = sorted(set(labels) - closure.keys())
    if missing:
        raise ValueError("Buck dependency closure omitted requested targets: " + ", ".join(missing))
    forbidden = [(label, kind) for label, kind in sorted(closure.items())
                 if kind in FORBIDDEN_KINDS or label in FORBIDDEN_LABELS]
    return closure, forbidden


def check(selection):
    """Return nonzero unless a complete unconfigured closure contains no proof rule."""
    try:
        labels = requested(selection)
        query = "deps(set(" + " ".join(json.dumps(label) for label in labels) + "))"
        result = subprocess.run([
            "buck2", "uquery", query, "--json", "--output-attribute", r"^buck\.type$",
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        if result.returncode:
            print("Cannot verify proof-free CI targets: Buck dependency query failed.", file=sys.stderr)
            if result.stderr:
                print(result.stderr.rstrip(), file=sys.stderr)
            return 1
        closure, forbidden = inspect_closure(json.loads(result.stdout), labels)
        if forbidden:
            print("CI selection includes forbidden proof dependencies:", file=sys.stderr)
            for label, kind in forbidden:
                print(f"  {label} ({kind})", file=sys.stderr)
            return 1
        print(f"Proof-free CI selection: {len(labels)} requested targets, {len(closure)} dependency targets.")
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Cannot verify proof-free CI targets: {error}", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    try:
        selection = json.loads(args.manifest.read_text())
    except (OSError, ValueError) as error:
        print(f"Cannot read CI selection: {error}", file=sys.stderr)
        return 1
    return check(selection)


if __name__ == "__main__":
    raise SystemExit(main())
