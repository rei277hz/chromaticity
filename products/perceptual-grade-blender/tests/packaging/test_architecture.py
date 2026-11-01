"""Enforce intact private component packages and headless dependency boundaries."""
from importlib.resources import files
import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
import zipfile


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.tree = Path(str(files('tests.packaging') / 'extension_tree'))
        self.archive = files('tests.packaging') / 'perceptual_grade.zip'

    def test_archive_has_only_the_declared_private_component_closure(self):
        with zipfile.ZipFile(self.archive) as archive:
            names = set(archive.namelist())
        components = {'color_core', 'invariant', 'blender_runtime', 'perceptual_grade_core', 'perceptual_grade_blender'}
        actual = {name.split('/')[0] for name in names if '/' in name}
        self.assertEqual(actual, components)
        for component in components:
            self.assertIn(component + '/__init__.py', names)
        self.assertIn('__init__.py', names)
        self.assertFalse(any(name.startswith('_vendor/') for name in names))
        public_python = {name for name in names if name.endswith('.py') and '/' not in name}
        self.assertEqual(public_python, {'__init__.py'})
        self.assertFalse(any(name.startswith(('core/', 'blender/', 'perceptual_grade/', 'color_tools/'))
                             for name in names))
        contracts = {'invariant/verification/__init__.py',
                     'invariant/verification/runtime_contracts.py'}
        self.assertFalse(any(set(Path(name).parts) & {'compiler', 'verification', 'z3', 'INVARIANT'}
                             for name in names - contracts))
        self.assertTrue(contracts <= names)
        self.assertIn('blender_runtime/app.py', names)
        self.assertIn('blender_runtime/ownership/arena.py', names)
        self.assertIn('blender_runtime/blender/registration.py', names)
        self.assertIn('invariant/actors.py', names)
        self.assertFalse(any(name.startswith(('invariant/ownership/',
                                             'invariant/execution/',
                                             'invariant/blender/')) for name in names))

    def test_core_imports_are_headless_and_do_not_depend_on_adapters(self):
        cores = ('color_core', 'perceptual_grade_core', 'invariant')
        hosts = ('blender_runtime.blender', 'perceptual_grade_blender')
        bad_roots = {'bpy', 'gpu', 'gpu_extras', 'blf', 'mathutils', 'z3',
                     'invariant_compiler', 'invariant_verification'}
        bad_roots.update('pg_arch.' + name for name in hosts)
        paths = [path for component in cores for path in
                 sorted((self.tree / component).rglob('*.py'))
                 if component != 'invariant' or 'blender' not in path.relative_to(self.tree / component).parts]
        self.assertTrue(paths, 'The headless check must inspect actual packaged sources')
        for path in paths:
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    package = '.'.join(('pg_arch', *path.relative_to(self.tree).parent.parts))
                    relative = '.' * node.level + (node.module or '')
                    modules = [importlib.util.resolve_name(relative, package) if node.level
                               else (node.module or '')]
                    modules.extend(modules[0] + '.' + alias.name for alias in node.names)
                else:
                    continue
                for module in modules:
                    # App's explicitly configured native capability is a lazy import.
                    if path.name == 'app.py' and module.startswith('pg_arch.blender_runtime.blender'):
                        continue
                    self.assertFalse(any(module == root or module.startswith(root + '.')
                                         for root in bad_roots),
                                     f'{path}: core imports adapter/Blender module {module}')

        script = textwrap.dedent(f'''
            import sys
            sys.path[:] = {list(sys.path)!r}
            import importlib, importlib.abc, importlib.util
            from pathlib import Path
            class Forbidden(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    blocked = {tuple(sorted(bad_roots))!r}
                    if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
                        raise AssertionError('headless core imported forbidden host module: ' + fullname)
            sys.meta_path.insert(0, Forbidden())
            root = {str(self.tree)!r}
            spec = importlib.util.spec_from_file_location('pg_arch', root + '/__init__.py',
                submodule_search_locations=[root])
            package = importlib.util.module_from_spec(spec)
            sys.modules['pg_arch'] = package
            spec.loader.exec_module(package)
            for component in {cores!r}:
                for path in sorted(Path(root, component).rglob('*.py')):
                    if component == 'invariant' and 'blender' in path.relative_to(Path(root, component)).parts:
                        continue
                    parts = path.relative_to(root).with_suffix('').parts
                    if parts[-1] == '__init__':
                        parts = parts[:-1]
                    importlib.import_module('pg_arch.' + '.'.join(parts))
            assert not any(name == blocked or name.startswith(blocked + '.')
                           for name in sys.modules for blocked in {tuple(sorted(bad_roots))!r})
        ''')
        result = subprocess.run([sys.executable, '-B', '-c', script], text=True,
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_scope_identity_consumers_do_not_use_positional_keys(self):
        paths = [path for path in self.tree.rglob('*.py')
                 if path.name in {'scheduler.py', 'sampling.py'} or 'cloud' in path.name]
        violations = []
        for path in paths:
            tree = ast.parse(path.read_text(), filename=str(path))
            for function in (node for node in ast.walk(tree)
                             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
                nodes = []
                def collect(node):
                    if node is not function and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                        return
                    nodes.append(node)
                    for child in ast.iter_child_nodes(node):
                        collect(child)
                collect(function)
                aliases = {'_scope_key', 'scope_key'}
                def identity(node):
                    if isinstance(node, ast.Name):
                        return node.id in aliases
                    return (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                            and (node.slice.value == '_scope_key' or
                                 (node.slice.value == 'key' and isinstance(node.value, ast.Name)
                                  and node.value.id == 'spec')))
                for _ in range(len(nodes)):
                    previous = set(aliases)
                    for node in nodes:
                        if isinstance(node, ast.Assign) and identity(node.value):
                            aliases.update(target.id for target in node.targets if isinstance(target, ast.Name))
                    if aliases == previous:
                        break
                for node in nodes:
                    if not isinstance(node, ast.Subscript) or not identity(node.value):
                        continue
                    index = node.slice
                    numeric = isinstance(index, ast.Constant) and type(index.value) is int
                    negative = (isinstance(index, ast.UnaryOp) and isinstance(index.op, ast.USub)
                                and isinstance(index.operand, ast.Constant) and type(index.operand.value) is int)
                    if numeric or negative or isinstance(index, ast.Slice):
                        violations.append(f'{path}:{node.lineno}: {ast.unparse(node)}')
        self.assertFalse(violations, '\n'.join(violations))
