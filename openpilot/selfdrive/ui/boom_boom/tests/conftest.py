import os
import tempfile

# the package's store must never touch a real device's or developer's settings during tests
_tmp = tempfile.TemporaryDirectory(prefix="boom_boom_test_")
os.environ["BOOM_BOOM_DIR"] = _tmp.name
