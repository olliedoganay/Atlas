import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from atlas_local.code_runner import CodeRunner, RunPlan, _runner_network_policy, _runner_timeout_seconds


class CodeRunnerPolicyTests(unittest.TestCase):
    def test_default_network_is_isolated_for_non_gui_runs(self) -> None:
        plan = RunPlan(image="python:3.12-slim", filename="main.py", command=["python", "/work/main.py"])

        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(_runner_network_policy(plan), "none")

    def test_gui_runs_force_bridge_network_for_vnc_port(self) -> None:
        plan = RunPlan(
            image="atlas-python-gui:latest",
            filename="main.py",
            command=["python", "/work/main.py"],
            ports={12345: 6080},
            gui=True,
        )

        with patch.dict("os.environ", {"ATLAS_RUNNER_NETWORK": "none"}):
            self.assertEqual(_runner_network_policy(plan), "bridge")

    def test_timeout_policy_uses_env_override(self) -> None:
        plan = RunPlan(image="python:3.12-slim", filename="main.py", command=["python", "/work/main.py"])

        with patch.dict("os.environ", {"ATLAS_RUNNER_TIMEOUT_SECONDS": "7"}):
            self.assertEqual(_runner_timeout_seconds(plan), 7)

    def test_start_adds_runner_safety_docker_flags(self) -> None:
        captured: dict[str, list[str]] = {}

        class FakeProcess:
            stdout: list[str] = []
            stderr: list[str] = []

            def wait(self) -> int:
                return 0

            def kill(self) -> None:
                return None

        def fake_popen(args, **_kwargs):
            captured["args"] = args
            return FakeProcess()

        with tempfile.TemporaryDirectory() as tmp:
            plan = RunPlan(image="python:3.12-slim", filename="main.py", command=["python", "/work/main.py"])
            with (
                patch("atlas_local.code_runner._docker_binary", return_value="docker"),
                patch("atlas_local.code_runner.resolve_plan", return_value=plan),
                patch("atlas_local.code_runner.subprocess.Popen", side_effect=fake_popen),
                patch(
                    "atlas_local.code_runner.subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
                ),
                patch("atlas_local.code_runner.tempfile.mkdtemp", return_value=tmp),
            ):
                response = CodeRunner().start("python", "print('hello')")

        args = captured["args"]
        self.assertIn("--network", args)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertIn("--security-opt", args)
        self.assertIn("no-new-privileges", args)
        self.assertIn("--cap-drop", args)
        self.assertIn("ALL", args)
        self.assertIn("atlas.runner=1", args)
        self.assertEqual(response["network"], "none")
        self.assertEqual(response["timeout_seconds"], 120)


if __name__ == "__main__":
    unittest.main()
