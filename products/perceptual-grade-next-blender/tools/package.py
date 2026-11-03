"""Build the verified Perceptual Grade Blender extension ZIP."""

import argparse
import hashlib
import json
from pathlib import Path

from verification.packaging import package, sources


def _verify_proof(proof, tree, requirements, source, label):
    proof = Path(proof)
    report_bytes = (proof / "report.json").read_bytes()
    receipt = json.loads((proof / "receipt.json").read_text())
    report = json.loads(report_bytes)
    source_bytes = sources(tree)[source]
    requirement_bytes = Path(requirements).read_bytes()
    if report.get("ok") is not True:
        raise ValueError(label + " proof did not pass")
    if receipt.get("source_sha256") != hashlib.sha256(source_bytes).hexdigest():
        raise ValueError(label + " proof does not match the packaged policy source")
    if receipt.get("requirements_sha256") != hashlib.sha256(requirement_bytes).hexdigest():
        raise ValueError(label + " proof does not match its requirements")
    if receipt.get("report_sha256") != hashlib.sha256(report_bytes).hexdigest():
        raise ValueError(label + " proof report does not match its receipt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tree", "output-dir", "inventory"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("stack", "readiness", "preparation"):
        parser.add_argument("--proof-" + name, type=Path, required=True)
        parser.add_argument("--requirements-" + name, type=Path, required=True)
    args = parser.parse_args()
    for name, source in (
        ("stack", "policy/stack.py"),
        ("readiness", "policy/readiness.py"),
        ("preparation", "policy/preparation.py"),
    ):
        _verify_proof(getattr(args, "proof_" + name), args.tree,
                      getattr(args, "requirements_" + name), source,
                      name.replace("_", " ").title())
    package(args.tree, args.output_dir / "perceptual_grade.zip",
            inventory_path=args.inventory)


if __name__ == "__main__":
    main()
