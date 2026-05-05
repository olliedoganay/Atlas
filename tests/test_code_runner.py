import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from atlas_local.code_runner import (
    CodeRunner,
    LANGUAGES,
    LEGACY_PYTHON_GUI_IMAGES,
    PYTHON_GUI_IMAGE,
    RunPlan,
    resolve_plan,
    _remove_legacy_python_gui_images,
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

    def test_gui_start_keeps_only_package_install_capabilities(self) -> None:
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
            plan = RunPlan(
                image=PYTHON_GUI_IMAGE,
                filename="main.py",
                command=["sh", "-c", "echo gui"],
                ports={12345: 6080},
                gui=True,
            )
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
                CodeRunner().start("python", "print('hello')")

        args = captured["args"]
        added_caps = [
            args[index + 1]
            for index, value in enumerate(args)
            if value == "--cap-add" and index + 1 < len(args)
        ]
        self.assertEqual(added_caps, ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"])

    def test_docker_commands_do_not_use_login_shells(self) -> None:
        for language, spec in LANGUAGES.items():
            with self.subTest(language=language):
                if len(spec.command) >= 2 and spec.command[0] == "sh":
                    self.assertNotEqual(spec.command[1], "-lc")

    def test_cleanup_removes_only_legacy_python_gui_images(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args, **_kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("atlas_local.code_runner.subprocess.run", side_effect=fake_run):
            _remove_legacy_python_gui_images("docker")

        removed_images = [args[-1] for args in calls]
        self.assertEqual(removed_images, list(LEGACY_PYTHON_GUI_IMAGES))
        self.assertNotIn(PYTHON_GUI_IMAGE, removed_images)

    def test_python_gui_uses_disposable_base_image_and_runtime_dependencies(self) -> None:
        plan = resolve_plan("python", "import tkinter\nroot = tkinter.Tk()\nroot.mainloop()")

        self.assertEqual(PYTHON_GUI_IMAGE, "python:3.12-slim")
        self.assertIn("atlas-python-gui:workspace1", LEGACY_PYTHON_GUI_IMAGES)
        self.assertIn("atlas-python-gui:workspace2", LEGACY_PYTHON_GUI_IMAGES)
        self.assertNotIn(PYTHON_GUI_IMAGE, LEGACY_PYTHON_GUI_IMAGES)
        self.assertEqual(plan.image, PYTHON_GUI_IMAGE)
        self.assertIn("apt-get install", plan.command[-1])
        self.assertIn("session.screen0.workspaces: 1", plan.command[-1])
        self.assertIn("fluxbox -rc /root/.fluxbox/init", plan.command[-1])
        self.assertIn("tcl8.6", plan.command[-1])
        self.assertIn("tk8.6", plan.command[-1])

    def test_python_gui_plan_installs_gui_dependencies_on_demand(self) -> None:
        plan = resolve_plan("python", "import pygame\npygame.display.set_mode((400, 300))")

        self.assertEqual(plan.image, PYTHON_GUI_IMAGE)
        self.assertTrue(plan.gui)

    def test_tkinter_import_uses_gui_runner_for_system_tk_deps(self) -> None:
        plan = resolve_plan("python", "import tkinter as tk\nprint('cli mode')")

        self.assertEqual(plan.image, PYTHON_GUI_IMAGE)
        self.assertTrue(plan.gui)

    def test_tkinter_from_import_uses_gui_runner_for_system_tk_deps(self) -> None:
        plan = resolve_plan("python", "from tkinter import ttk\nprint('cli mode')")

        self.assertEqual(plan.image, PYTHON_GUI_IMAGE)
        self.assertTrue(plan.gui)

    def test_direct_tkinter_window_uses_gui_runner(self) -> None:
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

        plan = resolve_plan("python", code)

        self.assertTrue(plan.gui)
        self.assertIn("python -u /tmp/main.py --gui", plan.command[-1])


if __name__ == "__main__":
    unittest.main()
