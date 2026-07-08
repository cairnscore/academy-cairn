import os

import pytest

CAIRN_TEST_URL = os.environ.get("CAIRN_TEST_URL")
pytestmark = pytest.mark.skipif(not CAIRN_TEST_URL, reason="set CAIRN_TEST_URL to run")
