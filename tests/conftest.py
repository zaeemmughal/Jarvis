"""Keep test runs from writing into the real reports/ and data/ folders."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import config, modes  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="jarvis-test-")
config.REPORTS_DIR = os.path.join(_tmp, "reports")
modes._PATH = os.path.join(_tmp, "mode.txt")
