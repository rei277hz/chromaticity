"""Enforce the shipped component graph and the framework's internal boundaries."""
import ast
from importlib.resources import files
import importlib.util
import json
from pathlib import Path
import sys
import unittest


RETIRED = frozenset({
    'execution_core', 'execution_blender', 'ownership_core',
    'ownership_blender', 'integration_blender', 'blender_shared',
})
PRODUCTS = frozenset({'perceptual_grade_blender', 'perceptual_grade_next_blender',
                      'hdr_color_picker_blender'})
MATH = frozenset({'color_core', 'perceptual_grade_core',
                  'hdr_color_picker_core', 'perceptual_grade_reference'})
BUILD_ONLY = frozenset({'invariant_compiler', 'invariant_verification', 'z3', 'z3solver'})
NATIVE = frozenset({'bpy', 'gpu', 'gpu_extras', 'blf', 'mathutils'})
CAPABILITIES = frozenset({'execution', 'ownership', 'blender'})


def bundles():
    resources = Path(str(files(__package__)))
    for manifest in sorted(resources.glob('*.json')):
        yield manifest.stem, resources / manifest.stem, json.loads(manifest.read_text())


def components_for(tree):
    return {path.name for path in tree.iterdir() if path.is_dir()}


def sources():
    for bundle, tree, components in bundles():
        for component, spec in components.items():
            for name in spec['files']:
                if name.endswith('.py'):
                    path = tree / component / name
                    yield bundle, tree, component, spec, name, ast.parse(path.read_text(), filename=str(path))


def imports(tree, package):
    """Return resolved imports with their eager/lazy position, without importing Blender."""
    def visit(node, lazy=False):
        lazy = lazy or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        if isinstance(node, ast.Import):
            for row in node.names:
                yield row.name, False, lazy
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = importlib.util.resolve_name('.' * node.level + (node.module or ''), package)
                # `from .. import component` names the owner in its imported list.
                targets = [base + '.' + row.name for row in node.names] if (
                    base in ('color_tools', 'extension') or
                    base.endswith('.blender_runtime') and any(row.name in CAPABILITIES for row in node.names)
                ) else [base]
                for target in targets:
                    yield target, True, lazy
            elif node.module:
                yield node.module, False, lazy
        for child in ast.iter_child_nodes(node):
            yield from visit(child, lazy)
    yield from visit(tree)


class ComponentTests(unittest.TestCase):
    def test_color_core_has_no_component_dependencies(self):
        found = False
        for bundle, _, component, spec, name, syntax in sources():
            if component != 'color_core':
                continue
            found = True
            package = ('color_tools.color_core.' + name[:-3].replace('/', '.')).rsplit('.', 1)[0]
            with self.subTest(bundle=bundle, source=name):
                self.assertEqual(spec['dependencies'], [])
                for target, relative, _ in imports(syntax, package):
                    if relative:
                        self.assertTrue(target.startswith('color_tools.color_core.'), target)
                    else:
                        self.assertIn(target.split('.')[0], {'numpy'} | sys.stdlib_module_names, target)
        self.assertTrue(found)

    def test_imports_follow_declared_component_dependencies_in_both_namespaces(self):
        checked = set()
        for bundle, tree, component, spec, name, syntax in sources():
            checked.add(component)
            for namespace in ('color_tools', 'extension'):
                module = namespace + '.' + component + '.' + name[:-3].replace('/', '.')
                package = module.rsplit('.', 1)[0]
                with self.subTest(bundle=bundle, component=component, source=name, namespace=namespace):
                    for target, relative, lazy in imports(syntax, package):
                        parts = target.split('.')
                        self.assertFalse(RETIRED.intersection(parts), 'Retired component import: ' + target)
                        self.assertFalse(BUILD_ONLY.intersection(parts), 'Build-only dependency in runtime: ' + target)
                        if not relative:
                            if (name.rsplit('/', 1)[-1].startswith('_') and name.endswith('_contracts.py')
                                    and target == 'invariant.verification.runtime_contracts' and lazy):
                                continue  # Shared Machine supplies the private package's binder.
                            self.assertNotIn(parts[0], {'color_tools', 'perceptual_grade', 'hdr_color_picker', 'invariant'} | PRODUCTS | MATH,
                                             'Application/component imports must be relocatable')
                            continue
                        self.assertTrue(target.startswith(namespace + '.'), target)
                        component_parts = target[len(namespace) + 1:].split('.')
                        owner = component_parts[0]
                        if owner != component:
                            self.assertIn(owner, spec['dependencies'], f'{target} requires a direct Buck dependency')
                        location = tree.joinpath(*component_parts)
                        optional = (component == 'blender_runtime' and name == 'app.py' and lazy
                                    and component_parts in (['blender_runtime', 'ownership'], ['blender_runtime', 'blender'])
                                    and not PRODUCTS.intersection(components_for(tree)))
                        self.assertTrue(optional or location.is_dir() or location.with_suffix('.py').is_file(), target)
        self.assertTrue({'color_core', 'perceptual_grade_core', 'perceptual_grade_reference'} <= checked, checked)

    def test_retired_and_build_only_packages_are_absent_from_runtime_closures(self):
        for name, _, components in bundles():
            with self.subTest(bundle=name):
                self.assertFalse(RETIRED.intersection(components))
                self.assertFalse(BUILD_ONLY.intersection(components))
                for component, spec in components.items():
                    self.assertFalse(RETIRED.intersection(spec['dependencies']), component)
                    for path in spec['files']:
                        parts = set(Path(path).parts)
                        allowed_contract = (component == 'invariant' and path in
                                            ('verification/__init__.py', 'verification/runtime_contracts.py'))
                        forbidden = {'compiler', 'proofs', 'INVARIANT'} | (set() if allowed_contract else {'verification'})
                        self.assertFalse(parts & forbidden, path)
                        self.assertFalse(parts & BUILD_ONLY, path)
                if name == 'hdr-color-picker-blender':
                    self.assertFalse(any(owner.startswith('perceptual_grade') for owner in components))
                if name == 'perceptual-grade-blender':
                    self.assertFalse(any(owner.startswith('hdr_color_picker') for owner in components))
                if name == 'perceptual-grade-next-blender':
                    self.assertFalse(any(owner in {'perceptual_grade_core', 'perceptual_grade_blender'}
                                         for owner in components))

    def test_math_and_framework_layers_have_no_product_or_native_backedges(self):
        for bundle, _, component, spec, name, syntax in sources():
            if component not in MATH | {'invariant', 'blender_runtime'}:
                continue
            package = 'color_tools.' + component + '.' + name[:-3].replace('/', '.')
            package = package.rsplit('.', 1)[0]
            with self.subTest(bundle=bundle, component=component, source=name):
                self.assertFalse(PRODUCTS.intersection(spec['dependencies']))
                if component in MATH | {'invariant'}:
                    self.assertNotIn('blender_runtime', spec['dependencies'])
                for target, _, lazy in imports(syntax, package):
                    parts = target.split('.')
                    self.assertFalse(PRODUCTS.intersection(parts), target)
                    native_layer = component == 'blender_runtime' and name.startswith('blender/')
                    if not native_layer:
                        self.assertFalse(NATIVE.intersection(parts), target)
                    if component in MATH and len(parts) > 2 and parts[:2] == ['color_tools', 'invariant']:
                        self.assertNotIn(parts[2], CAPABILITIES, 'Math may depend only on the invariant ABI and machine policies')
                    if component == 'blender_runtime' and parts[:2] == ['color_tools', 'blender_runtime'] and len(parts) > 2:
                        dependency = parts[2]
                        layer = name.split('/')[0]
                        if layer in {'execution', 'ownership'}:
                            self.assertNotIn(dependency, CAPABILITIES - {layer}, target)
                        elif layer == 'policies':
                            self.assertNotIn(dependency, CAPABILITIES, target)
                        elif '/' not in name and dependency in CAPABILITIES:
                            self.assertTrue(lazy, 'Optional capabilities must not load during ABI import: ' + target)

    def test_machine_policies_have_no_runtime_or_compiler_imports(self):
        found = False
        for bundle, _, component, _, name, syntax in sources():
            if not any('/' + folder + '/' in '/' + name for folder in ('policies', 'coordinators')):
                continue
            if name.rsplit('/', 1)[-1].startswith('_') and name.endswith('_contracts.py'):
                continue
            found = True
            with self.subTest(bundle=bundle, component=component, source=name):
                for node in ast.walk(syntax):
                    if isinstance(node, ast.ImportFrom):
                        self.assertEqual(node.level, 0)
                        self.assertIn(node.module, {'dataclasses', 'typing'})
                        allowed = {'dataclasses': {'dataclass', 'replace'}, 'typing': {'Literal'}}
                        self.assertLessEqual({alias.name for alias in node.names}, allowed[node.module])
                    elif isinstance(node, ast.Import):
                        self.fail('Machine policies must use only explicit dataclass and Literal imports')
        if not found:
            self.skipTest('No reusable machine policies are present in this component bundle')


if __name__ == '__main__':
    unittest.main()
