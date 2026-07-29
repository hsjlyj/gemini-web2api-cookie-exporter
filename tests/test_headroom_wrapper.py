from __future__ import annotations

import os
import stat
import unittest
from pathlib import Path


class TestHeadroomWrapper(unittest.TestCase):
    def test_wrapper_exists_and_is_executable(self):
        wrapper = Path(__file__).resolve().parents[1] / "scripts" / "headroom"
        self.assertTrue(wrapper.exists(), msg=f"missing wrapper: {wrapper}")
        self.assertTrue(os.access(wrapper, os.X_OK), msg=f"wrapper not executable: {wrapper}")
        mode = wrapper.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)

    def test_default_headroom_dir_points_to_local_checkout(self):
        default = "/root/headroom"
        exists = Path(default).exists()
        if not exists:
            self.skipTest("local headroom checkout not available in this environment")
        self.assertTrue((Path(default) / "pyproject.toml").exists())


if __name__ == "__main__":
    unittest.main()
