"""Check report coverage against declared source inputs without rendering the book.

This checks traceability. Reviewers still establish that prose matches behavior.
The module is build-only and is never a dependency of the installed extension.
"""

from pathlib import Path, PurePosixPath

from pg_book_build.assemble import _summary_chapters
from pg_book_build.book_refs import comment_references, source_anchors


PRODUCT = "products/perceptual-grade-next-blender"
SCOPES = frozenset({"next", "reference", "legacy", "mixed", "shared"})
POLICY_KINDS = frozenset({"production", "comparison", "mixed", "conceptual"})
CONCEPTUAL = frozenset({"next-policy.overview", "next-policy.contract"})


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


def _records(value, key, label):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a nonempty list")
    result = {}
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError(f"{label} entries must be records")
        name = _text(entry.get(key), f"{label}.{key}")
        if name in result:
            raise ValueError(f"Duplicate {label} entry: {name}")
        result[name] = entry
    return result


def _paths(value, label, roots, *, required=True):
    if not isinstance(value, list) or (required and not value):
        raise ValueError(f"{label} must be {'a nonempty' if required else 'a'} list")
    result = set()
    for name in value:
        _text(name, label)
        relative = PurePosixPath(name)
        if (relative.is_absolute() or ".." in relative.parts
                or relative.as_posix() != name):
            raise ValueError(f"Invalid evidence path: {name}")
        if name in result:
            raise ValueError(f"Duplicate evidence path in {label}: {name}")
        matches = [(prefix, Path(root)) for prefix, root in roots.items()
                   if name.startswith(prefix + "/")]
        if not matches:
            raise ValueError(f"Undeclared evidence path: {name}")
        prefix, root = max(matches, key=lambda item: len(item[0]))
        if not (root / name[len(prefix) + 1:]).is_file():
            raise ValueError(f"Missing evidence path: {name}")
        result.add(name)
    return result


def _is_test(name):
    return (name.startswith(PRODUCT + "/") and name.endswith(".py")
            and "tests" in PurePosixPath(name).parts[len(PurePosixPath(PRODUCT).parts):]
            and PurePosixPath(name).name.startswith("test_"))


def audit_report(manifest, docs, roots):
    """Validate chapter scope, policy references, and shipped-policy coverage.

    ``docs`` is the authored book root; ``roots`` maps repository-relative
    prefixes to declared Buck source resources. No runtime modules are imported.
    """
    if (not isinstance(manifest, dict) or type(manifest.get("schema")) is not int
            or manifest["schema"] != 1):
        raise ValueError("Expected report audit schema 1")
    chapters = _records(manifest.get("chapters"), "path", "chapter")
    source_root = Path(docs) / "src"
    expected = set(_summary_chapters(source_root / "report/SUMMARY.md"))
    if set(chapters) != expected:
        raise ValueError(f"Report chapter coverage: missing={sorted(expected - chapters.keys())}, "
                         f"extra={sorted(chapters.keys() - expected)}")

    anchors = {}
    for name, chapter in chapters.items():
        if chapter.get("scope") not in SCOPES:
            raise ValueError(f"Invalid chapter scope: {name}")
        _text(chapter.get("review"), f"{name}.review")
        _paths(chapter.get("evidence"), f"{name}.evidence", roots)
        remaining = chapter.get("remaining_work")
        if (not isinstance(remaining, list)
                or (chapter["scope"] in {"legacy", "mixed"} and not remaining)):
            raise ValueError(f"{name}: legacy/mixed scope needs remaining_work")
        for item in remaining:
            _text(item, f"{name}.remaining_work")
        path = source_root / ("report/README.md" if name == "README.md" else name)
        for anchor in source_anchors(path.read_text(encoding="utf-8"), name):
            identifier = anchor["anchor"]
            if identifier in anchors:
                raise ValueError(f"Duplicate report anchor: {identifier}")
            anchors[identifier] = name

    policies = _records(manifest.get("policies"), "anchor", "policy")
    expected_policies = {name for name in anchors if name.startswith("next-policy.")}
    if policies.keys() != expected_policies:
        raise ValueError(f"Policy anchor coverage: missing={sorted(expected_policies - policies.keys())}, "
                         f"extra={sorted(policies.keys() - expected_policies)}")

    product_root = Path(roots[PRODUCT])
    references = {}
    for directory in ("src", "examples", "tools"):
        for path in sorted((product_root / directory).rglob("*.py")):
            name = PRODUCT + "/" + path.relative_to(product_root).as_posix()
            references[name] = set()
            for item in comment_references(path.read_text(encoding="utf-8"), name):
                if not item["reference"].startswith("technical-report/en#"):
                    continue
                anchor = item["reference"].split("#", 1)[1]
                if anchor not in anchors:
                    raise ValueError(f"Unresolved report anchor in {name}: {anchor}")
                references[name].add(anchor)

    covered = set()
    for anchor, policy in policies.items():
        if policy.get("kind") not in POLICY_KINDS:
            raise ValueError(f"Invalid policy kind: {anchor}")
        conceptual = policy["kind"] == "conceptual"
        if conceptual != (anchor in CONCEPTUAL):
            raise ValueError(f"Only overview and contract are conceptual: {anchor}")
        sources = _paths(policy.get("sources"), f"{anchor}.sources", roots,
                         required=not conceptual)
        evidence = _paths(policy.get("evidence"), f"{anchor}.evidence", roots,
                          required=not conceptual)
        if conceptual and (sources or evidence):
            raise ValueError(f"Conceptual anchor has no implementation callers: {anchor}")
        if any(not _is_test(name) for name in evidence):
            raise ValueError(f"{anchor}: policy evidence must name Next Python tests")
        for source in sources:
            if anchor not in references.get(source, set()):
                raise ValueError(f"Missing source comment for {anchor}: {source}")
        covered.update(sources)

    shipped = {PRODUCT + "/" + path.relative_to(product_root).as_posix()
               for path in (product_root / "src/policy").rglob("*.py")
               if path.name != "__init__.py"}
    if not shipped:
        raise ValueError("Report audit needs a nonempty shipped policy source tree")
    if missing := shipped - covered:
        raise ValueError(f"Shipped policies missing report coverage: {sorted(missing)}")
    return {"chapters": len(chapters), "policy_sections": len(policies),
            "shipped_policies": len(shipped)}
