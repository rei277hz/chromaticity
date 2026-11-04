"""Build the verified Perceptual Grade Blender extension ZIP."""

import argparse
import json
from pathlib import Path

from verification.invariant_report import InvariantProofs
from verification.packaging import package, sources


def verify_policy_coverage(entries, manifest):
    """Every shipped policy module must have source-bound build evidence."""
    expected = {name for name in entries
                if name.startswith("policy/") and name.endswith(".py")
                and Path(name).name != "__init__.py"}
    if (not isinstance(manifest, dict) or manifest.get("version") != 2
            or not isinstance(manifest.get("machines"), dict)):
        raise ValueError("Invalid policy proof inventory")
    actual = {item["runtime_source"] for item in manifest["machines"].values()}
    if not expected or actual != expected:
        raise ValueError("Policy proof coverage differs from shipped modules: "
                         f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")


def build(tree, output_dir, inventory, proofs):
    output_dir = Path(output_dir)
    try:
        manifest = json.loads((Path(proofs) / "manifest.json").read_text())
        verify_policy_coverage(sources(tree), manifest)
        package(tree, output_dir / "perceptual_grade.zip", inventory_path=inventory,
                proof_requirement=InvariantProofs(Path(proofs)))
    except Exception:
        for name in ("perceptual_grade.zip", ".perceptual_grade.zip.candidate", "package-report.json"):
            (output_dir / name).unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tree", "output-dir", "inventory", "proofs"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    build(args.tree, args.output_dir, args.inventory, args.proofs)


if __name__ == "__main__":
    main()
