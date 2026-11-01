"""Native image cache checks without submitting or baking a LUT job."""
from tests.support.session import component as _component, SessionTest, patch
import json
from types import SimpleNamespace
pass

import bpy
import numpy as np
lut = _component('graph.lut')
from color_tools.perceptual_grade_core.model import color, forward, linear, tone, transforms
sampling = _component('scopes.sampling')
from tests.support.blender import BlenderTest


class LutCacheTests(BlenderTest):
    def test_recalibrated_shadow_anchor_rejects_prior_lut_and_scope_cache_identities(self):
        model=transforms.Stack([transforms.Settings(linear.I3,tone.Parameters(),
                                                   color.Parameters(),'Linear Rec.709')])
        previous=SimpleNamespace(space=model.space,
            bake_key=('stack-core',12,*model.bake_key[2:]))
        with patch.object(lut.cm,'SCHEMA',29):
            old_signature=lut.cm.signature(previous)
        self.assertNotEqual(lut.cm.signature(model),old_signature)
        # A valid native atlas cannot authorize output from the previous
        # numerical model, even when its saved control values match.
        manifest=dict(size=lut.cm.SIZE,signature=old_signature)
        with patch.object(lut,'_manifest',return_value=manifest), \
             patch.object(lut,'scope_rows',side_effect=AssertionError('Stale cube was admitted')):
            with self.assertRaisesRegex(ValueError,'Stale LUT model'):
                lut.validate_output(None,model,final=True)
        identity=sampling._evaluation_identity(True,None,None,linear.I3,
            model.space,model.space,sampling._model_identity(model))
        self.assertIn(f'forward-schema-{forward.SCHEMA}',identity)
        self.assertIn(f'lut-schema-{lut.cm.SCHEMA}',identity)
        self.assertEqual(sampling._model_identity(model)[:2],model.cache_key[:2])

    def image(self, value=.25, signature='cache-premise', *, produced=True):
        size = lut.cm.PREVIEW_SIZE
        cube = lut.cm.Cube(np.full((size, size, size, 3), value, np.float32),
                           signature, size=size)
        pixels = cube.packed_pixels()
        image = bpy.data.images.new('LUT cache premise', width=pixels.shape[1],
                                    height=pixels.shape[0], alpha=True, float_buffer=True)
        image.pixels.foreach_set(pixels.ravel())
        image['_pg_cube_schema'] = lut.SCHEMA
        image['_pg_cube_signature'] = signature
        image['_pg_cube_size'] = size
        image['_pg_cube_encoding'] = 'RGBE_DIFFERENCES'
        image[lut.resources.REVISION] = 'fixture-operation'
        if produced:
            ownership = _component('ownership')
            lut._cubes[image.as_pointer()] = (ownership.retain(image, 'test.cube'), cube,
                                             image[lut.resources.REVISION])
        return image, cube

    def test_repeated_produced_cube_reads_preserve_identity_without_native_decode(self):
        image, cube = self.image()
        with patch.object(lut.cm, 'unpack_rgbe', side_effect=AssertionError('Native decoding')), \
                patch.object(lut.resources, 'read_pixels', side_effect=AssertionError('Native readback')):
            self.assertTrue(all(lut.read_cube(image) is cube for _ in range(20)))

    def test_restored_metadata_cannot_supply_a_produced_cube(self):
        image, _ = self.image(produced=False)
        image[lut.resources.RECORD] = json.dumps(dict(version=1, phase='COMPLETE',
            source='cache-premise', operation_id='a'*32))
        with patch.object(lut.cm, 'unpack_rgbe', side_effect=AssertionError('Native decoding')), \
                patch.object(lut.resources, 'read_pixels', side_effect=AssertionError('Native readback')):
            self.assertIsNone(lut.read_cube(image))

    def test_distinct_resources_keep_distinct_produced_cubes(self):
        first_image, first = self.image(.25)
        second_image, second = self.image(.5)
        self.assertIs(lut.read_cube(first_image), first)
        self.assertIs(lut.read_cube(second_image), second)
        self.assertIsNot(first, second)

    def test_changed_signature_or_operation_revokes_cached_provenance(self):
        for name, value in (('_pg_cube_signature', 'external'),
                            (lut.resources.REVISION, 'new-operation')):
            image, cube = self.image()
            self.assertIs(lut.read_cube(image), cube)
            image[name] = value
            self.assertIsNone(lut.read_cube(image))

    def test_runtime_clear_does_not_decode_persisted_pixels(self):
        image, cube = self.image()
        self.assertIs(lut.read_cube(image), cube)
        lut.clear()
        self.assertIsNone(lut.read_cube(image))
