#!/usr/bin/env python3
"""Require next-blender proofs and keep CI validation within that product."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


MANIFEST = Path(__file__).with_name("targets.json")
PRODUCT = "//products/perceptual-grade-next-blender"
REQUIRED_PROOFS = PRODUCT + ":verify_policies"
REFERENCE_PROOFS = "//libraries/perceptual-grade-reference/proofs"
VALIDATION_KINDS = frozenset({"invariant_proof", "invariant_bundle", "verification_group"})
EXCLUDED_PROJECTS = (
    "//libraries/perceptual-grade-core",
    "//products/perceptual-grade-blender",
)


def within(label, root):
    package = label.split(":", 1)[0]
    return package == root or package.startswith(root + "/")


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
        outside = [label for label in labels if not within(label, PRODUCT)]
        if outside:
            raise ValueError("CI may select only next-blender targets: " + ", ".join(outside))
        result.extend(labels)
    if REQUIRED_PROOFS not in selection["builds"]:
        raise ValueError("CI builds must include " + REQUIRED_PROOFS)
    return sorted(set(result))


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
    # Ordinary source libraries may support product tests. They do not authorize
    # running another project's tests, proofs, or legacy generated proof actions.
    forbidden = [(label, kind) for label, kind in sorted(closure.items())
                 if ((kind in VALIDATION_KINDS or kind.endswith("_test"))
                     and not within(label, PRODUCT))
                 or within(label, REFERENCE_PROOFS)
                 or any(within(label, root + "/proofs")
                        or within(label, root) and kind == "generate"
                        for root in EXCLUDED_PROJECTS)]
    if closure.get(REQUIRED_PROOFS) != "verification_group":
        raise ValueError("The required product proof gate must be a verification_group")
    if not any(kind == "invariant_proof" and within(label, PRODUCT)
               for label, kind in closure.items()):
        raise ValueError("The CI dependency closure contains no next-blender policy proofs")
    return closure, forbidden


def check(selection):
    """Check the dependency graph without executing any build or validation action."""
    try:
        labels = requested(selection)
        query = "deps(set(" + " ".join(json.dumps(label) for label in labels) + "))"
        result = subprocess.run([
            "buck2", "uquery", query, "--json", "--output-attribute", r"^buck\.type$",
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        if result.returncode:
            print("Cannot verify next-blender CI targets: Buck dependency query failed.", file=sys.stderr)
            if result.stderr:
                print(result.stderr.rstrip(), file=sys.stderr)
            return 1
        closure, forbidden = inspect_closure(json.loads(result.stdout), labels)
        if forbidden:
            print("CI selection includes validation outside next-blender:", file=sys.stderr)
            for label, kind in forbidden:
                print(f"  {label} ({kind})", file=sys.stderr)
            return 1
        print(f"Next-blender CI selection (including policy proofs): {len(labels)} requested targets, {len(closure)} dependency targets.")
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Cannot verify next-blender CI targets: {error}", file=sys.stderr)
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
