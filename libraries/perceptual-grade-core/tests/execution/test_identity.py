"""Named scope identities stay immutable across the headless worker boundary."""
from copy import deepcopy
from dataclasses import dataclass, FrozenInstanceError, replace
import unittest

import numpy as np

from color_tools.perceptual_grade_core.jobs import codec
from color_tools.perceptual_grade_core.jobs.values import seal
from color_tools.perceptual_grade_core.model import color, linear, tone
from color_tools.perceptual_grade_core.scopes.identity import ActiveScopeIdentity, LinearScopeIdentity, ScopeIdentity


class ScopeIdentityTests(unittest.TestCase):
    def identity(self):
        return ScopeIdentity(version=('image', 3), reference_version=('reference', 7),
            comparison='difference', matrix=linear.I3, tone=tone.Parameters(),
            request_params=color.Parameters(), stack_signature=('grade', 9),
            generation=4, stage=3,
            presentation=ActiveScopeIdentity(schema=1, requested=('cloud',),
                views=(('cloud', 640, 480),), enabled=True))

    def test_seal_preserves_named_types_and_frozen_parameter_records(self):
        original = self.identity()
        sealed = seal(original)
        self.assertIs(type(sealed), ScopeIdentity)
        self.assertIs(type(sealed.presentation), ActiveScopeIdentity)
        self.assertIs(type(sealed.tone), tone.Parameters)
        self.assertIs(type(sealed.request_params), color.Parameters)
        self.assertEqual(sealed, original)
        self.assertEqual(hash(sealed), hash(original))
        self.assertIsNot(sealed, original)
        with self.assertRaises(FrozenInstanceError):
            sealed.generation = 20
        with self.assertRaises(FrozenInstanceError):
            sealed.presentation.enabled = False

    def test_request_and_result_codecs_keep_exact_identity_types_and_aliases(self):
        identity = self.identity()
        stage_one = LinearScopeIdentity(source=('image', 3, linear.GradeSpace()),
                                        reference=None, matrix=linear.I3)
        self.assertEqual(seal(stage_one), stage_one)
        for freeze, thaw in ((codec.freeze_scope_request, codec.thaw_scope_request),
                             (codec.freeze_scope_result, codec.thaw_scope_result)):
            with self.subTest(freeze=freeze.__name__):
                payload = seal(freeze({'key': identity, 'same': identity, 'linear': stage_one}))
                decoded = thaw(payload)
                self.assertIs(type(decoded['key']), ScopeIdentity)
                self.assertIs(type(decoded['key'].presentation), ActiveScopeIdentity)
                self.assertIs(type(decoded['linear']), LinearScopeIdentity)
                self.assertEqual(decoded['key'], identity)
                self.assertEqual(decoded['linear'], stage_one)
                self.assertIs(decoded['key'], decoded['same'])
                self.assertEqual(hash(decoded['key']), hash(identity))

    def test_stack_signature_is_excluded_only_from_declared_projections(self):
        original = self.identity()
        changed = replace(original, stack_signature=('grade', 10))
        self.assertEqual(original.scheduler_projection('evaluation'), changed.scheduler_projection('evaluation'))
        self.assertEqual(original.source_projection(), changed.source_projection())
        self.assertNotEqual(original.source_projection(stack=True), changed.source_projection(stack=True))
        self.assertNotEqual(original.analysis(), changed.analysis())
        arguments = ('owner', 'context', 'scene', 'grade')
        self.assertNotEqual(original.capture_projection(*arguments), changed.capture_projection(*arguments))

    def test_presentation_changes_display_without_invalidating_numerical_capture(self):
        original = self.identity()
        changed = original.with_presentation(replace(original.presentation, views=(('cloud', 800, 600),)))
        self.assertNotEqual(original, changed)
        self.assertEqual(original.analysis(), changed.analysis())
        self.assertEqual(original.source_projection(stack=True), changed.source_projection(stack=True))
        arguments = ('owner', 'context', 'scene', 'grade')
        self.assertEqual(original.capture_projection(*arguments), changed.capture_projection(*arguments))
        self.assertNotEqual(original.scheduler_projection('evaluation'), changed.scheduler_projection('evaluation'))
        self.assertIsNone(original.analysis().presentation)

    def test_control_generation_and_stage_changes_invalidate_scheduler_semantics(self):
        original = self.identity()
        for changed in (replace(original, tone=replace(original.tone, fit=1.)),
                        replace(original, generation=original.generation + 1),
                        replace(original, stage=2)):
            with self.subTest(changed=changed):
                self.assertNotEqual(original.scheduler_projection('evaluation'), changed.scheduler_projection('evaluation'))
                self.assertEqual(original.source_projection(), changed.source_projection())
        self.assertNotEqual(original.scheduler_projection('old'), original.scheduler_projection('new'))

    def test_whitelist_rejects_identity_subclasses_and_foreign_dataclasses(self):
        class DerivedIdentity(ScopeIdentity):
            pass
        @dataclass(frozen=True)
        class ForeignRecord:
            value: int = 1
        original = self.identity()
        derived = DerivedIdentity(**{name: getattr(original, name) for name in original.__dataclass_fields__})
        for invalid in (derived, ForeignRecord(), object()):
            for boundary in (seal, codec.freeze_scope_request, codec.freeze_scope_result):
                with self.subTest(invalid=type(invalid).__name__, boundary=boundary.__name__), self.assertRaises(TypeError):
                    boundary(invalid)

    def test_identity_fields_cannot_hide_mutable_arrays_containers_or_native_values(self):
        for invalid in (object(), {'native': object()}, ['mutable'], np.zeros(1), lambda: None):
            identity = replace(self.identity(), stack_signature=invalid)
            for boundary in (seal, codec.freeze_scope_request, codec.freeze_scope_result):
                with self.subTest(invalid=type(invalid).__name__, boundary=boundary.__name__), self.assertRaises(TypeError):
                    boundary(identity)

    def test_identity_parameters_cannot_hide_arbitrary_objects(self):
        malformed = replace(tone.Parameters(), fit=object())
        identity = replace(self.identity(), tone=malformed)
        for boundary in (seal, codec.freeze_scope_request, codec.freeze_scope_result):
            with self.subTest(boundary=boundary.__name__), self.assertRaises(TypeError):
                boundary(identity)

    def test_identity_grading_space_cannot_hide_arbitrary_objects(self):
        class DerivedSpace(linear.GradeSpace):
            pass
        for space in (linear.GradeSpace(preset=object()), DerivedSpace()):
            identity = LinearScopeIdentity(source=('image', space), reference=None,
                                           matrix=linear.I3)
            for boundary in (seal, codec.freeze_scope_request, codec.freeze_scope_result):
                with self.subTest(space=type(space).__name__, boundary=boundary.__name__), self.assertRaises(TypeError):
                    boundary(identity)

    def test_identity_cycles_are_rejected_at_both_boundaries(self):
        identity = self.identity()
        object.__setattr__(identity, 'stack_signature', identity)
        for boundary in (seal, codec.freeze_scope_request, codec.freeze_scope_result):
            with self.subTest(boundary=boundary.__name__), self.assertRaisesRegex(ValueError, 'cycles'):
                boundary(identity)

    def test_wire_identity_requires_known_fields_and_validated_values(self):
        payload = codec.freeze_scope_request(self.identity())
        root = payload['root']['ref']
        for name in ('extra', 'missing', 'mutable'):
            broken = deepcopy(payload)
            data = broken['records'][root]['data']
            if name == 'extra':
                data['unexpected'] = {'value': 0}
            elif name == 'missing':
                del data['generation']
            else:
                data['generation'] = {'value': ['mutable']}
            with self.subTest(name=name), self.assertRaises((TypeError, ValueError)):
                codec.thaw_scope_request(broken)

