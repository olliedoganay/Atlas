import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from atlas_local.code_runner import (
    CodeRunner,
    LANGUAGES,
    PYTHON_GUI_IMAGE,
    RunPlan,
    resolve_plan,
    _runner_network_policy,
    _runner_timeout_seconds,
)


class CodeRunnerPolicyTests(unittest.TestCase):
    def test_default_network_is_isolated_for_non_gui_runs(self) -> None:
        plan = RunPlan(image="python:3.12-slim", filename="main.py", command=["python", "/work/main.py"])

        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(_runner_network_policy(plan), "none")

    def test_gui_runs_force_bridge_network_for_vnc_port(self) -> None:
        plan = RunPlan(
            image=PYTHON_GUI_IMAGE,
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

    def test_docker_commands_do_not_use_login_shells(self) -> None:
        for language, spec in LANGUAGES.items():
            with self.subTest(language=language):
                if len(spec.command) >= 2 and spec.command[0] == "sh":
                    self.assertNotEqual(spec.command[1], "-lc")

    def test_python_gui_image_uses_single_fluxbox_workspace(self) -> None:
        dockerfile = Path("src/atlas_local/runner_images/python_gui.Dockerfile").read_text(encoding="utf-8")

        self.assertNotEqual(PYTHON_GUI_IMAGE, "atlas-python-gui:latest")
        self.assertIn("session.screen0.workspaces: 1", dockerfile)
        self.assertIn("fluxbox -rc /root/.fluxbox/init", dockerfile)

    def test_python_gui_plan_builds_image_on_demand(self) -> None:
        with patch("atlas_local.code_runner._ensure_python_gui_image") as ensure_image:
            plan = resolve_plan("python", "import pygame\npygame.display.set_mode((400, 300))")

        ensure_image.assert_called_once()
        self.assertEqual(plan.image, PYTHON_GUI_IMAGE)
        self.assertTrue(plan.gui)

    def test_tkinter_import_alone_does_not_force_gui_runner(self) -> None:
        plan = resolve_plan("python", "import tkinter as tk\nprint('cli mode')")

        self.assertEqual(plan.image, "python:3.12-slim")
        self.assertFalse(plan.gui)

    def test_direct_tkinter_window_uses_gui_runner(self) -> None:
        with patch("atlas_local.code_runner._ensure_python_gui_image"):
            plan = resolve_plan("python", "import tkinter\nroot = tkinter.Tk()\nroot.mainloop()")

        self.assertEqual(plan.image, PYTHON_GUI_IMAGE)
        self.assertTrue(plan.gui)

    def test_python_gui_plan_passes_gui_flag_when_declared(self) -> None:
        code = "\n".join(
            [
                "import argparse",
                "import tkinter as tk",
                "parser = argparse.ArgumentParser()",
                "parser.add_argument('--gui', action='store_true')",
                "args = parser.parse_args()",
                "if args.gui:",
                "    root = tk.Tk()",
                "    root.mainloop()",
                "else:",
                "    print('cli mode')",
            ],
        )

        with patch("atlas_local.code_runner._ensure_python_gui_image"):
            plan = resolve_plan("python", code)

        self.assertTrue(plan.gui)
        self.assertIn("python -u /tmp/main.py --gui", plan.command[-1])


if __name__ == "__main__":
    unittest.main()
