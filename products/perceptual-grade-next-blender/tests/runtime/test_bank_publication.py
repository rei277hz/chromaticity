"""Effect runner preserves policy order for fixed-bank publication."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


class BankPublicationRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-bank-publication-")
        root = Path(cls.directory.name)
        package = root / "grade_bank_publication_test"
        package.mkdir()
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))
        cls.runner = staticmethod(importlib.import_module(
            "grade_bank_publication_test.runtime.bank_publication"
        ).run_bank_publication)
        cls.result_type = importlib.import_module(
            "grade_bank_publication_test.runtime.bank_publication"
        ).PublicationResult

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_bank_publication_test" or name.startswith(
                    "grade_bank_publication_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def test_normal_publication_stages_inactive_bank_before_select_and_delivery(self):
        actions = []

        def operate(name):
            def run(bank, _errors):
                actions.append((name, bank))
                if name == "stage":
                    return {"clean": True}
                if name == "select":
                    return {"selected_bank": bank}
                if name == "deliver":
                    return {"delivered": True}
                return {}
            return run

        result = self.runner(
            0,
            {name: operate(name) for name in (
                "stage", "repair", "select", "deliver", "restore_selector",
                "fail_closed",
            )},
            admitted=True, active_valid=True,
        )
        self.assertEqual(result, self.result_type("committed", ()))
        self.assertEqual(actions, [("stage", 1), ("select", 1), ("deliver", 1)])

    def test_damaged_active_bank_requires_successful_close_before_repair(self):
        actions = []

        def fail_closed(_bank, _errors):
            actions.append("fail_closed")
            if actions.count("fail_closed") == 1:
                raise RuntimeError("first close attempt failed")
            return {"closed": True}

        def repair(bank, _errors):
            actions.append(("repair", bank))
            return {"clean": True}

        def select(bank, _errors):
            actions.append(("select", bank))
            return {"selected_bank": bank}

        def deliver(bank, _errors):
            actions.append(("deliver", bank))
            return {"delivered": True}

        result = self.runner(
            0,
            {"stage": lambda *_args: self.fail("ordinary stage must not run"),
             "repair": repair, "select": select, "deliver": deliver,
             "restore_selector": lambda *_args: {}, "fail_closed": fail_closed},
            admitted=True, active_valid=False,
        )
        self.assertEqual(result.outcome, "committed")
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(actions, ["fail_closed", "fail_closed", ("repair", 1),
                                   ("select", 1), ("deliver", 1)])

    def test_selector_failure_restores_active_bank_before_fail_closed(self):
        actions = []

        def select(bank, _errors):
            actions.append(("select", bank))
            return {"selected_bank": 0}

        def restore(bank, _errors):
            actions.append(("restore", bank))
            return {"selected_bank": bank}

        operations = {
            "stage": lambda _bank, _errors: {"clean": True},
            "repair": lambda *_args: self.fail("repair must not run"),
            "select": select,
            "deliver": lambda *_args: self.fail("delivery requires candidate readback"),
            "restore_selector": restore,
            "fail_closed": lambda _bank, _errors: (
                actions.append("fail_closed") or {"closed": True}
            ),
        }
        result = self.runner(
            0, operations, admitted=True, active_valid=True,
        )
        self.assertEqual(result, self.result_type("failed_closed", ()))
        self.assertEqual(actions, [("select", 1), ("restore", 0), "fail_closed"])

    def test_denied_publication_must_close_and_never_stage(self):
        actions = []

        def fail_closed(_bank, _errors):
            actions.append("fail_closed")
            return {"closed": True}

        result = self.runner(
            0,
            {"stage": lambda *_args: self.fail("denied work must not stage"),
             "repair": lambda *_args: self.fail("denied work must not repair"),
             "select": lambda *_args: self.fail("denied work must not select"),
             "deliver": lambda *_args: self.fail("denied work must not deliver"),
             "restore_selector": lambda *_args: self.fail("no selector changed"),
             "fail_closed": fail_closed},
            admitted=False, active_valid=True,
        )
        self.assertEqual(result, self.result_type("failed_closed", ()))
        self.assertEqual(actions, ["fail_closed"])

    def test_closure_never_invokes_a_third_attempt(self):
        for active_valid in (True, False):
            with self.subTest(active_valid=active_valid):
                actions = []

                def fail_closed(bank, _errors):
                    actions.append(("fail_closed", bank))
                    return {"closed": False}

                result = self.runner(
                    1, {"stage": lambda *_args: {"clean": False},
                        "fail_closed": fail_closed},
                    admitted=True, active_valid=active_valid,
                )
                self.assertEqual(actions, [("fail_closed", 1), ("fail_closed", 1)])
                self.assertEqual(result.outcome, "indeterminate")
                self.assertEqual([str(error) for error in result.errors[-3:]], [
                    "Grade failure output was not confirmed",
                    "Grade failure output was not confirmed",
                    "Could not establish the banked failure output",
                ])

    def test_repair_and_final_closure_each_allow_a_retry(self):
        actions = []
        close_receipts = iter((False, True, False, True))

        def fail_closed(bank, _errors):
            actions.append(("fail_closed", bank))
            return {"closed": next(close_receipts)}

        def repair(bank, _errors):
            actions.append(("repair", bank))
            return {"clean": False}

        result = self.runner(
            1, {"repair": repair, "fail_closed": fail_closed},
            admitted=True, active_valid=False,
        )
        self.assertEqual(actions, [
            ("fail_closed", 1), ("fail_closed", 1), ("repair", 0),
            ("fail_closed", 1), ("fail_closed", 1),
        ])
        self.assertEqual(result.outcome, "failed_closed")
        self.assertEqual([str(error) for error in result.errors], [
            "Grade failure output was not confirmed",
            "Banked helper image could not be packed cleanly",
            "Grade failure output was not confirmed",
        ])


if __name__ == "__main__":
    unittest.main()
