"""Exception diagnostics retain value data without subclass-owned objects."""
import unittest
from color_tools.blender_runtime.execution import diagnostics


class DiagnosticTests(unittest.TestCase):
    def test_failure_receipt_discards_string_subclass_attributes(self):
        class Text(str):
            pass

        class Exotic(ValueError):
            def __str__(self):
                value = Text('diagnostic')
                value.native_owner = object()
                return value

        error = Exotic()
        self.assertIs(type(str(error)), Text)
        self.assertIs(type(diagnostics.text(error)), str)
        receipt = diagnostics.Failure.capture(error)
        self.assertIs(type(receipt.type_name), str)
        self.assertIs(type(receipt.message), str)
        self.assertIs(type(receipt.detail), str)
        self.assertEqual(receipt.message, 'diagnostic')
