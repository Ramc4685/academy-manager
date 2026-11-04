"""Manual verification canary for the pytest-timeout backstop (issue #550).

Skipped by default because it deliberately sleeps past the configured
per-test timeout. To verify the backstop fires, remove the skip decorator
temporarily and run this file alone: it should be killed at ~120s with a
Timeout failure and a thread stack traceback.
"""

import time

import pytest


@pytest.mark.skip(reason="manual backstop verification only; deliberately exceeds the 120s cap")
def test_hanging_test_is_killed_by_backstop() -> None:
    time.sleep(130)  # exceeds the 120s addopts timeout
