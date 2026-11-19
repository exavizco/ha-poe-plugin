"""The fake board test helper itself."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_test_certs_leave_no_folder_behind(tmp_path):
    """make_cert's files go when the test process ends (#96).

    Each run used to leave one folder per certificate in the temp directory.
    """
    script = "from tests.fake_board import make_cert\nfor _ in range(3): make_cert()\n"
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={**os.environ, "TMPDIR": str(tmp_path)},
        check=True,
    )
    assert list(tmp_path.iterdir()) == []
