"""Ownership and import boundaries for the product-owned kernel component."""
import ast
import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).parent.parent
FORBIDDEN = frozenset({'perceptual_grade_reference', 'perceptual_grade_core',
                      'perceptual_grade_blender', 'perceptual_grade_next_blender',
                      'invariant'})
NATIVE = frozenset({'bpy', 'gpu', 'gpu_extras', 'blf', 'mathutils'})


class RejectNativeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split('.')[0] in NATIVE:
            raise AssertionError(f'Portable import attempted native dependency {fullname}')
        return None


class ArchitectureTests(unittest.TestCase):
    def test_component_closure_and_runtime_imports(self):
        manifest=json.loads((ROOT/'component_manifest.json').read_text())
        self.assertEqual(set(manifest),{'kernel','color_core'})
        component=manifest['kernel']
        self.assertEqual(component['dependencies'],['color_core'])
        self.assertTrue(component['owner'].endswith('//products/perceptual-grade-next-blender'))
        sources=ROOT/'component_sources'
        actual={str(path.relative_to(sources)) for path in sources.rglob('*.py')}
        self.assertEqual(actual,{path for path in component['files'] if path.endswith('.py')})
        self.assertEqual(set(component['files'])-actual,{'output_boundary.npz'})
        self.assertTrue((ROOT/'component_bundle'/'kernel'/'output_boundary.npz').is_file())
        for filename in sources.rglob('*.py'):
            module=ast.parse(filename.read_text())
            relative=filename.relative_to(sources)
            package='extension.kernel'
            if relative.parent.parts:
                package+='.'+'.'.join(relative.parent.parts)
            for node in ast.walk(module):
                if isinstance(node,ast.Import):
                    modules=[a.name for a in node.names]
                elif isinstance(node,ast.ImportFrom):
                    modules=[node.module or '']
                    if node.level:
                        target=importlib.util.resolve_name('.'*node.level+(node.module or ''),package)
                        self.assertTrue(target.startswith('extension.'),(filename,target))
                        owner=target.split('.')[1]
                        self.assertIn(owner,{'kernel',*component['dependencies']},(filename,target))
                        location=(ROOT/'component_bundle').joinpath(*target.split('.')[1:])
                        self.assertTrue(location.is_dir() or location.with_suffix('.py').is_file(),(filename,target))
                else:
                    continue
                for name in modules:
                    self.assertFalse(FORBIDDEN.intersection(name.split('.')),(filename,name))
                    if filename.name not in {'graph.py', 'persistent.py'}:
                        self.assertNotIn(name.split('.')[0],NATIVE,filename)
                    self.assertFalse(name.startswith('color_tools.'),(filename,name))

    def test_private_relocation_and_preparation_need_no_blender(self):
        """Exercise the private-extension import shape and portable entrypoint."""
        namespace='_grade_nodes_architecture_test'
        self.assertNotIn(namespace,sys.modules)
        package=types.ModuleType(namespace)
        package.__path__=[str(ROOT/'component_bundle')]
        guard=RejectNativeImports()
        before=set(sys.modules)
        sys.modules[namespace]=package
        sys.meta_path.insert(0,guard)
        try:
            api=importlib.import_module(namespace+'.kernel')
            graph=importlib.import_module(namespace+'.kernel.graph')
            persistent=importlib.import_module(namespace+'.kernel.persistent')
            prepared=api.prepare(tone=api.ToneSettings(input_nits=(0.,8.,40.,235.,1150.)))
            boundary=importlib.import_module(namespace+'.kernel.boundary')
            geometry=boundary.prepare_boundary(prepared.fl,prepared.aw,prepared.gamma)
            self.assertEqual(geometry.pixels.shape,(321,513,4))
            self.assertFalse(geometry.pixels.flags.writeable)
            self.assertEqual(prepared.space,'Linear Rec.709')
            self.assertEqual(prepared.table.cells,256)
            self.assertTrue(callable(graph.build_group))
            self.assertTrue(callable(persistent.build_persistent))
            self.assertFalse(NATIVE.intersection(set(sys.modules)-before))
            self.assertFalse(FORBIDDEN.intersection({name.split('.')[0] for name in set(sys.modules)-before}))
        finally:
            sys.meta_path.remove(guard)
            for name in tuple(sys.modules):
                if name == namespace or name.startswith(namespace+'.'):
                    del sys.modules[name]


if __name__ == '__main__':
    unittest.main()
