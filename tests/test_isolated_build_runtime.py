"""Real Docker cases run in the explicit CI executor lane; no mocked PASS."""
import base64
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from utils.isolated_execution import DockerExecutor, validate_request, package_files
from utils.research_runtime import RuntimeStore


class BuildContractTests(unittest.TestCase):
    def test_paths_and_runtime_are_not_model_controlled_shell_arguments(self):
        for name in ("../secret", "/etc/passwd", "a/../../b.py", "a\\b.py", ".infinity-runner.py", "a//b.py"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_request("python", {name: "pass"}, name)
        with self.assertRaises(ValueError):
            validate_request("sh", {"main.py": "pass"}, "main.py")
        with self.assertRaises(ValueError):
            validate_request("python", {"a": "x", "a/main.py": "pass"}, "a/main.py")

    def test_disabled_executor_never_runs_code_on_host(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"INFINITY_BUILD_EXECUTOR": ""}):
            executor = DockerExecutor(RuntimeStore(Path(root)/"state.sqlite3"))
            canary = Path(root)/"must-not-exist"
            with patch('utils.isolated_execution.subprocess.Popen', side_effect=AssertionError("must not execute")):
                result = executor.run("python", {"main.py": f"open({str(canary)!r}, 'w').write('bad')"}, "main.py")
            self.assertEqual(result["state"], "BLOCKED")
            self.assertFalse(canary.exists())

    def test_source_archive_is_reproducible_and_downloadable(self):
        a = package_files({"src/main.py": "print(3)"})
        b = package_files({"src/main.py": "print(3)"})
        self.assertEqual(a["sha256"], b["sha256"])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(a["content"]))) as archive:
            self.assertEqual(archive.read("src/main.py"), b"print(3)")


@unittest.skipUnless(os.environ.get("INFINITY_REAL_EXECUTOR_TEST") == "1",
                     "real container execution is a separate required CI lane")
class RealBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.executor = DockerExecutor(RuntimeStore(Path(self.temp.name)/"state.sqlite3"))

    def run_code(self, code, extra=None):
        return self.executor.run("python", {"main.py": code, **(extra or {})}, "main.py")

    def test_multifile_app_build_returns_actual_artifact(self):
        result = self.run_code("from helper import title\nfrom pathlib import Path\nPath('index.html').write_text('<h1>'+title+'</h1>')\nprint('BUILD_OK')", {"helper.py": "title='Infinity demo'"})
        self.assertEqual(result["state"], "EXECUTED", result)
        self.assertTrue(result["cleanup_confirmed"])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result["artifact"]["content"]))) as archive:
            self.assertEqual(archive.read("output/index.html"), b"<h1>Infinity demo</h1>")
            self.assertIn("source/helper.py", archive.namelist())

    def test_host_secrets_network_privilege_and_cgroup_limits(self):
        code = '''
import os, socket
from pathlib import Path
assert os.getuid() == 65534
assert 'INFINITY_TEST_SECRET' not in os.environ
assert not Path('/var/run/docker.sock').exists()
try:
    assert not Path('/root/.ssh').exists()
except PermissionError: pass
try:
    Path('/etc/escape').write_text('bad')
    raise AssertionError('root filesystem was writable')
except OSError: pass
s = socket.socket(); s.settimeout(.2)
try:
    s.connect(('192.0.2.1', 443))
    raise AssertionError('network escaped')
except OSError: pass
status=Path('/proc/self/status').read_text()
assert 'NoNewPrivs:\\t1' in status
assert 'Seccomp:\\t2' in status
assert 'CapEff:\\t0000000000000000' in status
assert Path('/sys/fs/cgroup/memory.max').read_text().strip() == '268435456'
assert Path('/sys/fs/cgroup/pids.max').read_text().strip() == '32'
print('ISOLATION_CHECKS_OK')
'''
        with patch.dict(os.environ, {"INFINITY_TEST_SECRET": "HOST_ONLY_CANARY"}):
            result = self.run_code(code)
        self.assertEqual(result["state"], "EXECUTED", result)
        self.assertIn("ISOLATION_CHECKS_OK", result["stdout"])
        self.assertNotIn("HOST_ONLY_CANARY", json.dumps(result))

    def test_failed_program_and_symlink_have_no_success_artifact(self):
        for code in ("raise ValueError('expected failure')", "import os\nos.symlink('/etc/passwd','escape')"):
            result = self.run_code(code)
            self.assertEqual(result["state"], "FAILED", result)
            self.assertIsNone(result["artifact"])
            self.assertTrue(result["cleanup_confirmed"])

    def test_output_flood_is_bounded_and_container_removed(self):
        result = self.run_code("while True: print('x'*1000)")
        self.assertEqual(result["state"], "FAILED", result)
        self.assertIsNone(result["artifact"])
        self.assertLessEqual(len(result["stdout"]), 64000)
        self.assertTrue(result["cleanup_confirmed"])

    def test_wall_timeout_is_enforced_outside_generated_code(self):
        with patch('utils.isolated_execution.WALL_SECONDS', 1):
            result = self.run_code("while True: pass")
        self.assertEqual(result["state"], "FAILED", result)
        self.assertEqual(result["failure"], "wall_time_limit")
        self.assertTrue(result["cleanup_confirmed"])

    def test_runs_have_fresh_workspaces(self):
        first = self.run_code("open('private.txt','w').write('first-run')")
        second = self.run_code("from pathlib import Path\nassert not Path('private.txt').exists()")
        self.assertEqual(first["state"], "EXECUTED", first)
        self.assertEqual(second["state"], "EXECUTED", second)

    def test_node_build_returns_real_downloadable_html(self):
        result = self.executor.run("node", {"main.js": "require('fs').writeFileSync('/work/index.html','<h1>Node build</h1>')"}, "main.js")
        self.assertEqual(result["state"], "EXECUTED", result)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result["artifact"]["content"]))) as archive:
            self.assertEqual(archive.read("output/index.html"), b"<h1>Node build</h1>")


if __name__ == '__main__':
    unittest.main()
