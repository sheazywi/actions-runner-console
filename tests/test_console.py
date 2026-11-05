import contextlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from runner_console import common, hooks
from runner_console.lock import CollectorLock
from runner_console.process import runner_active


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runner = self.root / "runner"
        (self.runner / "_diag/pages").mkdir(parents=True)
        self.data = self.root / "data"
        common.configure(self.runner, self.data)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps(dict(runner_dir=str(self.runner), data_dir=str(self.data))))

    def test_hooks_capture_only_allowlisted_job_metadata(self):
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "42", "GITHUB_JOB": "compile",
                                    "GITHUB_WORKFLOW": "Example", "TEST_SECRET": "unit-test-private-marker"}):
            common.hook("started")
            started = common.read_json("job.json")["started"]
            common.hook("completed")
        job = common.read_json("job.json")
        self.assertEqual(job["run_id"], "42")
        self.assertEqual(job["started"], started)
        self.assertEqual(job["status"], "completed")
        self.assertNotIn("unit-test-private-marker", (self.data / "job.json").read_text())

    def test_concurrent_status_replacement(self):
        common.atomic("probe.json", {"n": 0, "payload": "x" * 8192})
        errors = []
        def writer():
            try:
                for n in range(200):
                    common.atomic("probe.json", {"n": n, "payload": "x" * 8192})
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=writer)
        thread.start()
        try:
            while thread.is_alive():
                record = common.read_json("probe.json")
                if record:
                    self.assertIsInstance(record["n"], int)
                    self.assertEqual(record["payload"], "x" * 8192)
        finally:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(common.read_json("probe.json")["n"], 199)

    def test_collector_uses_masked_pages_and_step_names(self):
        common.atomic("job.json", {"status": "started", "run_id": "42", "job": "compile", "started": 1})
        (self.runner / "_diag/Worker_example.log").write_text(
            "[2026-01-01 12:00:00Z INFO StepsRunner] Processing step: DisplayName='Build'\n")
        (self.runner / "_diag/pages/timeline_root_1.log").write_text("compiler output: ***\n")
        with patch("runner_console.process.runner_active", return_value=True), patch("runner_console.common.time.sleep", side_effect=KeyboardInterrupt):
            with contextlib.suppress(KeyboardInterrupt):
                common.collect()
        state = common.read_json("status.json")
        self.assertEqual(state["step"], "Build")
        self.assertEqual(state["status"], "BUILDING")
        self.assertIn("compiler output: ***", (self.data / "live.log").read_text())

    def test_existing_hooks_require_consent_and_restore_without_clobbering_changes(self):
        app = self.root / "app" / "runner_console"
        app.mkdir(parents=True)
        file_patch = patch("runner_console.hooks.__file__", str(app / "hooks.py"))
        file_patch.start()
        self.addCleanup(file_patch.stop)
        env = self.runner / ".env"
        env.write_text("KEEP=initial\nACTIONS_RUNNER_HOOK_JOB_STARTED=/original/hook\n")
        with self.assertRaises(RuntimeError):
            hooks.install(self.runner, self.data, self.config)
        hooks.install(self.runner, self.data, self.config, replace=True)
        env.write_text(env.read_text().replace("KEEP=initial", "KEEP=changed"))
        hooks.uninstall(self.runner, self.data)
        self.assertIn("KEEP=changed", env.read_text())
        self.assertIn("ACTIONS_RUNNER_HOOK_JOB_STARTED=/original/hook", env.read_text())
        self.assertNotIn("ACTIONS_RUNNER_HOOK_JOB_COMPLETED=", env.read_text())

    def test_only_one_collector_can_own_a_data_directory(self):
        with CollectorLock(self.data):
            with self.assertRaises(RuntimeError):
                CollectorLock(self.data)

    def test_process_detection_is_scoped_to_runner_directory(self):
        self.assertFalse(runner_active(self.runner))

    def test_log_control_sequences_are_not_emitted(self):
        self.assertEqual(common.clean("\x1b[31mred\x1b[0m\x00\x07"), "red")

    def test_platform_metrics(self):
        if os.name == "nt":
            from runner_console import windows as display
        else:
            from runner_console import linux as display
        used, total = display.memory()
        self.assertGreater(total, 0)
        self.assertGreaterEqual(used, 0)
        self.assertLessEqual(used, total)
        self.assertEqual(len(display.cpu()), 2)


if __name__ == "__main__":
    unittest.main()
