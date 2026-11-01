"""Focused native retry cases from the full recovery suite."""

import unittest

from . import test_recovery


CASES = (
    'test_recovery_waits_for_actual_retirement_and_retry_keeps_ownership_epoch',
    'test_pre_cleanup_failure_still_accepts_real_native_post',
)


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(test_recovery.RecoveryTests(name) for name in CASES)
