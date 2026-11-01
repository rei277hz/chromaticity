"""Validate the canonical Next requirement inventory against live proof inputs.

This is an inventory consistency check, not a theorem prover. In particular, a
reference to a proved policy or bounded projection does not establish that the
Blender adapter implements the entire canonical requirement.
"""

import argparse
import ast
from collections import Counter
import json
from pathlib import Path, PurePosixPath
import re


STATUSES = frozenset({"proved", "partial", "adapter_premise", "open"})
ID_PATTERN = re.compile(r"([SJTFRBU])(\d{2})(?:\s*[–-]\s*([SJTFRBU])(\d{2}))?")


class InventoryError(ValueError):
    """The canonical requirement inventory is incomplete or inconsistent."""


def canonical_ids(design):
    """Expand only the ID column of the canonical tables in design section 13."""
    section = re.search(r"^## 13\..*?(?=^## \d+\.|\Z)", design, re.M | re.S)
    if section is None:
        raise InventoryError("canonical design section 13 is missing")
    identifiers = []
    for line in section.group(0).splitlines():
        if not line.startswith("|"):
            continue
        match = ID_PATTERN.fullmatch(line.split("|")[1].strip())
        if match is None:
            continue
        first_family, first, last_family, last = match.groups()
        if last_family is not None and last_family != first_family:
            raise InventoryError("canonical range crosses requirement families")
        start, stop = int(first), int(last or first)
        if stop < start:
            raise InventoryError("canonical range is reversed")
        identifiers.extend(f"{first_family}{index:02d}" for index in range(start, stop + 1))
    if not identifiers:
        raise InventoryError("canonical design tables contain no requirement IDs")
    duplicates = sorted(key for key, count in Counter(identifiers).items() if count > 1)
    if duplicates:
        raise InventoryError(f"duplicate canonical design IDs: {duplicates}")
    return set(identifiers)


def _proof_targets(source, path):
    """Read literal invariant_proof declarations without executing Starlark."""
    declarations = {}
    try:
        parsed = ast.parse(source, filename=path)
    except SyntaxError as error:
        raise InventoryError(f"cannot parse proof declarations in {path}: {error}") from error
    for node in ast.walk(parsed):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "invariant_proof":
            continue
        fields = {}
        for keyword in node.keywords:
            if keyword.arg in {"name", "requirements", "source", "required_properties"}:
                try:
                    fields[keyword.arg] = ast.literal_eval(keyword.value)
                except (ValueError, TypeError) as error:
                    raise InventoryError(
                        f"{path}: {keyword.arg} must be literal for inventory validation"
                    ) from error
        name = fields.get("name")
        if not isinstance(name, str) or name in declarations:
            raise InventoryError(f"{path}: invalid or duplicate invariant proof name {name!r}")
        declarations[name] = fields
    return declarations


def _nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def validate(crosswalk, design, read_source, read_evidence=None):
    """Return counts after validating the crosswalk using repository-relative reads."""
    if not isinstance(crosswalk, dict) or crosswalk.get("version") != 1:
        raise InventoryError("crosswalk version must be 1")
    entries = crosswalk.get("requirements")
    if not isinstance(entries, list):
        raise InventoryError("crosswalk requirements must be a list")
    proof_catalog = crosswalk.get("proof_catalog")
    if not isinstance(proof_catalog, dict):
        raise InventoryError("crosswalk proof_catalog must be an object")
    gap_catalog = crosswalk.get("gap_catalog")
    if not isinstance(gap_catalog, dict):
        raise InventoryError("crosswalk gap_catalog must be an object")
    if any(not isinstance(entry, dict) for entry in entries):
        raise InventoryError("each crosswalk requirement must be an object")
    identifiers = [entry.get("id") for entry in entries]
    if any(not isinstance(identifier, str) for identifier in identifiers):
        raise InventoryError("every requirement needs a string ID")
    duplicates = sorted(key for key, count in Counter(identifiers).items() if count > 1)
    if duplicates:
        raise InventoryError(f"duplicate crosswalk IDs: {duplicates}")
    expected = canonical_ids(design)
    actual = set(identifiers)
    if expected != actual:
        raise InventoryError(
            f"canonical ID mismatch: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    inventories, targets = {}, {}
    for entry in entries:
        identifier = entry["id"]
        status = entry.get("status")
        if status not in STATUSES:
            raise InventoryError(f"{identifier}: invalid status {status!r}")
        if not _nonempty_text(entry.get("claim")):
            raise InventoryError(f"{identifier}: claim is required")
        proof_aliases = entry.get("proofs")
        evidence = entry.get("adapter_evidence", [])
        premises = entry.get("adapter_premises", [])
        gaps = entry.get("remaining_gaps")
        for field, value in (("proofs", proof_aliases), ("adapter_evidence", evidence),
                             ("adapter_premises", premises), ("remaining_gaps", gaps)):
            if not isinstance(value, list):
                raise InventoryError(f"{identifier}: {field} must be a list")
        for field, value in (("adapter_evidence", evidence), ("adapter_premises", premises),
                             ("remaining_gaps", gaps)):
            if any(not _nonempty_text(item) for item in value):
                raise InventoryError(f"{identifier}: {field} must contain nonempty strings")
        if evidence and read_evidence is None:
            raise InventoryError(f"{identifier}: adapter evidence cannot be checked")
        for evidence_path in evidence:
            path = PurePosixPath(evidence_path)
            if path.is_absolute() or ".." in path.parts:
                raise InventoryError(f"{identifier}: evidence paths must be repository-relative")
            try:
                read_evidence(evidence_path)
            except (OSError, KeyError) as error:
                raise InventoryError(f"{identifier}: missing adapter evidence {evidence_path}") from error
        for gap in gaps:
            if gap not in gap_catalog or not _nonempty_text(gap_catalog.get(gap)):
                raise InventoryError(f"{identifier}: unknown or unexplained gap {gap!r}")
        if status in {"proved", "partial"} and not proof_aliases:
            raise InventoryError(f"{identifier}: {status} requires a proof reference")
        if status == "proved" and gaps:
            raise InventoryError(f"{identifier}: proved requirements cannot have remaining gaps")
        if status != "proved" and not gaps:
            raise InventoryError(f"{identifier}: {status} requires a remaining-gap explanation")
        if status == "adapter_premise" and (not evidence or not premises):
            raise InventoryError(f"{identifier}: adapter_premise requires evidence and explicit premises")
        if not proof_aliases and not evidence and not gaps:
            raise InventoryError(f"{identifier}: requirement has no evidence or explained gap")
        seen = set()
        for alias in proof_aliases:
            if not isinstance(alias, str) or alias not in proof_catalog:
                raise InventoryError(f"{identifier}: unknown proof alias {alias!r}")
            proof = proof_catalog[alias]
            if not isinstance(proof, dict):
                raise InventoryError(f"proof catalog entry {alias!r} must be an object")
            if any(not _nonempty_text(proof.get(key))
                   for key in ("target", "requirements", "property", "scope")):
                raise InventoryError(f"{identifier}: proof needs target, requirements, property and scope")
            key = (proof["target"], proof["property"])
            if key in seen:
                raise InventoryError(f"{identifier}: duplicate proof reference {key}")
            seen.add(key)
            match = re.fullmatch(r"//([^:]+):([^:\[\]]+)", proof["target"])
            if match is None:
                raise InventoryError(f"{identifier}: invalid proof target {proof['target']!r}")
            package, target_name = match.groups()
            inventory_path = proof["requirements"]
            for source_path in (package, inventory_path):
                parsed_path = PurePosixPath(source_path)
                if parsed_path.is_absolute() or ".." in parsed_path.parts:
                    raise InventoryError(f"{identifier}: paths must be repository-relative")
            buck_path = f"{package}/BUCK"
            if buck_path not in targets:
                targets[buck_path] = _proof_targets(read_source(buck_path), buck_path)
            target = targets[buck_path].get(target_name)
            if target is None:
                raise InventoryError(f"{identifier}: missing invariant proof target {proof['target']}")
            if target.get("requirements") != str(PurePosixPath(inventory_path).relative_to(package)):
                raise InventoryError(f"{identifier}: {proof['target']} uses a different requirements file")
            if inventory_path not in inventories:
                inventory = json.loads(read_source(inventory_path))
                names = [prop["name"] for prop in inventory.get("properties", [])]
                if len(names) != len(set(names)):
                    raise InventoryError(f"duplicate property names in {inventory_path}")
                inventories[inventory_path] = set(names)
            if proof["property"] not in inventories[inventory_path]:
                raise InventoryError(f"{identifier}: missing .inv property {proof['property']}")
            if proof["property"] not in target.get("required_properties", []):
                raise InventoryError(
                    f"{identifier}: {proof['target']} does not require {proof['property']}"
                )
    return {
        "version": 1,
        "canonical_requirement_count": len(entries),
        "status_counts": {status: sum(entry["status"] == status for entry in entries)
                          for status in sorted(STATUSES)},
        "validated_proof_targets": sorted({proof_catalog[alias]["target"]
                                           for entry in entries for alias in entry["proofs"]}),
        "notice": "Inventory consistency only; partial, adapter-premise and open entries are not proof of the full canonical claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof-inputs", type=Path, required=True)
    parser.add_argument("--adapter-inputs", type=Path, required=True)
    parser.add_argument("--adapter-test-inputs", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    def read_evidence(path):
        try:
            return (args.adapter_inputs / path).read_bytes()
        except OSError:
            return (args.adapter_test_inputs / path).read_bytes()

    result = validate(json.loads(args.crosswalk.read_text()), args.design.read_text(),
                      lambda path: (args.proof_inputs / path).read_text(), read_evidence)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
