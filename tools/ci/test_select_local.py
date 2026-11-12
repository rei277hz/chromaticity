"""Verify local Buck configuration conversion in disposable checkouts."""

import unittest

from chromaticity_tools.ci import select_local


class LocalConfigTests(unittest.TestCase):
    def test_accepts_current_and_legacy_nativelink_markers(self):
        for begin in (
            "# BEGIN NativeLink settings\n",
            "# BEGIN NativeLink settings (managed by remote_execution/re)\n",
        ):
            with self.subTest(begin=begin):
                original = (
                    "[project]\n  ignore = buck-out\n\n"
                    + begin
                    + "[build]\n  execution_platforms = toolchains//:platforms\n\n"
                    + "[buck2_re_client]\n  engine_address = example:50051\n\n"
                    + "[remote_execution]\n  enabled = true\n"
                    + "  worker_image = sha256:abc\n"
                    + "# END NativeLink settings\n"
                    + "\n[other]\n  setting = kept\n"
                )

                result = select_local.local_config(original)

                self.assertIn("[project]\n  ignore = buck-out", result)
                self.assertIn("[other]\n  setting = kept", result)
                self.assertIn(select_local.BEGIN, result)
                self.assertIn("execution_platforms = prelude//platforms:default", result)
                self.assertIn("enabled = false", result)
                self.assertNotIn("example:50051", result)
                self.assertNotIn("worker_image", result)
                self.assertNotIn("NativeLink", result)

    def test_generic_conversion_is_idempotent(self):
        original = "[project]\n  ignore = buck-out\n"
        converted = select_local.local_config(original)

        self.assertEqual(select_local.local_config(converted), converted)

    def test_rejects_malformed_or_unmanaged_settings(self):
        cases = (
            select_local.BEGIN,
            select_local.END,
            select_local.END + select_local.BEGIN,
            select_local.BEGIN + select_local.BEGIN + select_local.END,
            "[remote_execution]\n  enabled = true\n",
        )
        for original in cases:
            with self.subTest(original=original), self.assertRaises(RuntimeError):
                select_local.local_config(original)


if __name__ == "__main__":
    unittest.main()
