from __future__ import annotations

import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class LanguageSpec:
    image: str
    filename: str
    command: list[str]
    needs_compile: bool = False


@dataclass
class RunPlan:
    image: str
    filename: str
    command: list[str]
    ports: dict[int, int] = field(default_factory=dict)  # host:container
    gui: bool = False


PYTHON_GUI_IMAGE = "atlas-python-gui:latest"
PYTHON_GUI_MARKERS = (
    "pygame",
    "tkinter",
    "turtle",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "wx",
    "kivy",
    "matplotlib.pyplot",
    "plt.show",
)
NOVNC_CONTAINER_PORT = 6080


def _python_gui_detected(code: str) -> bool:
    lowered = code
    for marker in PYTHON_GUI_MARKERS:
        pattern = rf"(?:^|[^A-Za-z0-9_]){re.escape(marker)}(?:[^A-Za-z0-9_]|$)"
        if re.search(pattern, lowered):
            return True
    return False


def _reserve_host_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


LANGUAGES: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        image="python:3.12-slim",
        filename="main.py",
        command=[
            "sh",
            "-lc",
            (
                "set -e; cp /work/main.py /tmp/main.py; cd /tmp; "
                "PY_IMPORTS=$(python - <<'PY'\n"
                "import ast, sys\n"
                "STDLIB = set(sys.stdlib_module_names)\n"
                "ALIAS = {'cv2':'opencv-python','sklearn':'scikit-learn','PIL':'Pillow','bs4':'beautifulsoup4','yaml':'PyYAML','skimage':'scikit-image'}\n"
                "src = open('/tmp/main.py').read()\n"
                "try:\n"
                "    tree = ast.parse(src)\n"
                "except SyntaxError:\n"
                "    sys.exit(0)\n"
                "pkgs = set()\n"
                "for node in ast.walk(tree):\n"
                "    if isinstance(node, ast.Import):\n"
                "        for n in node.names:\n"
                "            pkgs.add(n.name.split('.')[0])\n"
                "    elif isinstance(node, ast.ImportFrom):\n"
                "        if node.module and node.level == 0:\n"
                "            pkgs.add(node.module.split('.')[0])\n"
                "needed = sorted({ALIAS.get(p, p) for p in pkgs if p and p not in STDLIB})\n"
                "print(' '.join(needed))\n"
                "PY\n"
                "); "
                "if [ -n \"$PY_IMPORTS\" ]; then echo \"[atlas-runner] installing: $PY_IMPORTS\"; pip install --quiet --no-input --disable-pip-version-check --root-user-action=ignore $PY_IMPORTS || true; fi; "
                "python /tmp/main.py"
            ),
        ],
    ),
    "javascript": LanguageSpec(
        image="node:20-alpine",
        filename="main.js",
        command=[
            "sh",
            "-lc",
            (
                "set -e; mkdir -p /tmp/app; cp /work/main.js /tmp/app/main.js; cd /tmp/app; "
                "DEPS=$(node -e \"const fs=require('fs');const src=fs.readFileSync('/tmp/app/main.js','utf8');const core=new Set(require('module').builtinModules);const s=new Set();const re=/require\\(['\\\"]([^'\\\"]+)['\\\"]\\)|from ['\\\"]([^'\\\"]+)['\\\"]|import ['\\\"]([^'\\\"]+)['\\\"]/g;let m;while((m=re.exec(src))){let p=m[1]||m[2]||m[3];if(!p||p.startsWith('.')||p.startsWith('/')||p.startsWith('node:'))continue;if(p.startsWith('@')){p=p.split('/').slice(0,2).join('/')}else{p=p.split('/')[0]}if(!core.has(p))s.add(p)}process.stdout.write([...s].join(' '))\"); "
                "if [ -n \"$DEPS\" ]; then echo \"[atlas-runner] installing: $DEPS\"; npm init -y >/dev/null 2>&1; npm install --silent --no-audit --no-fund $DEPS >/dev/null 2>&1 || true; fi; "
                "node /tmp/app/main.js"
            ),
        ],
    ),
    "typescript": LanguageSpec(
        image="node:20-alpine",
        filename="main.ts",
        command=[
            "sh",
            "-lc",
            (
                "set -e; mkdir -p /tmp/app; cp /work/main.ts /tmp/app/main.ts; cd /tmp/app; "
                "DEPS=$(node -e \"const fs=require('fs');const src=fs.readFileSync('/tmp/app/main.ts','utf8');const core=new Set(require('module').builtinModules);const s=new Set();const re=/require\\(['\\\"]([^'\\\"]+)['\\\"]\\)|from ['\\\"]([^'\\\"]+)['\\\"]|import ['\\\"]([^'\\\"]+)['\\\"]/g;let m;while((m=re.exec(src))){let p=m[1]||m[2]||m[3];if(!p||p.startsWith('.')||p.startsWith('/')||p.startsWith('node:'))continue;if(p.startsWith('@')){p=p.split('/').slice(0,2).join('/')}else{p=p.split('/')[0]}if(!core.has(p))s.add(p)}process.stdout.write([...s].join(' '))\"); "
                "npm init -y >/dev/null 2>&1; "
                "if [ -n \"$DEPS\" ]; then echo \"[atlas-runner] installing: $DEPS\"; npm install --silent --no-audit --no-fund $DEPS >/dev/null 2>&1 || true; fi; "
                "npx --yes tsx /tmp/app/main.ts"
            ),
        ],
    ),
    "go": LanguageSpec(
        image="golang:1.22-alpine",
        filename="main.go",
        command=[
            "sh",
            "-lc",
            (
                "set -e; mkdir -p /tmp/app; cp /work/main.go /tmp/app/main.go; cd /tmp/app; "
                "go mod init atlasrun >/dev/null 2>&1 || true; "
                "echo '[atlas-runner] resolving modules'; "
                "go mod tidy >/dev/null 2>&1 || true; "
                "go run ."
            ),
        ],
    ),
    "rust": LanguageSpec(
        image="rust:1-slim",
        filename="main.rs",
        command=[
            "sh",
            "-lc",
            (
                "set -e; mkdir -p /tmp/app/src; cp /work/main.rs /tmp/app/src/main.rs; cd /tmp/app; "
                "printf '[package]\\nname=\"atlasrun\"\\nversion=\"0.1.0\"\\nedition=\"2021\"\\n' > Cargo.toml; "
                "CRATES=$(grep -E '^[[:space:]]*(use |extern crate )' src/main.rs | sed -E 's/^[[:space:]]*use |^[[:space:]]*extern crate //' | awk '{print $1}' | sed -E 's/([A-Za-z0-9_]+).*/\\1/' | sort -u | grep -Ev '^(std|core|alloc|crate|self|super)$' || true); "
                "if [ -n \"$CRATES\" ]; then echo \"[atlas-runner] installing: $CRATES\"; which cargo-add >/dev/null 2>&1 || true; for c in $CRATES; do cargo add $c >/dev/null 2>&1 || true; done; fi; "
                "cargo run --quiet 2>&1"
            ),
        ],
    ),
    "c": LanguageSpec(
        image="gcc:latest",
        filename="main.c",
        command=["sh", "-lc", "cp /work/main.c /tmp/main.c && gcc /tmp/main.c -o /tmp/app -lm && /tmp/app"],
    ),
    "cpp": LanguageSpec(
        image="gcc:latest",
        filename="main.cpp",
        command=["sh", "-lc", "cp /work/main.cpp /tmp/main.cpp && g++ /tmp/main.cpp -o /tmp/app -lm && /tmp/app"],
    ),
    "java": LanguageSpec(
        image="openjdk:21-slim",
        filename="Main.java",
        command=["sh", "-lc", "cp /work/Main.java /tmp/Main.java && cd /tmp && javac Main.java && java Main"],
    ),
    "ruby": LanguageSpec(
        image="ruby:3-alpine",
        filename="main.rb",
        command=[
            "sh",
            "-lc",
            (
                "set -e; apk add --no-cache build-base >/dev/null 2>&1 || true; "
                "cp /work/main.rb /tmp/main.rb; cd /tmp; "
                "GEMS=$(ruby -e \"src=File.read('/tmp/main.rb'); core=%w[date time json yaml fileutils pathname set open-uri securerandom digest base64 csv open3 tempfile timeout uri net/http net/https stringio strscan logger optparse ostruct singleton thread]; gs=src.scan(/^\\s*require\\s+['\\\"]([^'\\\"]+)['\\\"]/).flatten.map{|s|s.split('/').first}.uniq - core; puts gs.join(' ')\"); "
                "if [ -n \"$GEMS\" ]; then echo \"[atlas-runner] installing: $GEMS\"; gem install --silent --no-document $GEMS >/dev/null 2>&1 || true; fi; "
                "ruby /tmp/main.rb"
            ),
        ],
    ),
    "php": LanguageSpec(
        image="composer:2",
        filename="main.php",
        command=[
            "sh",
            "-lc",
            (
                "set -e; mkdir -p /tmp/app; cp /work/main.php /tmp/app/main.php; cd /tmp/app; "
                "PKGS=$(php -r '$s=file_get_contents(\"/tmp/app/main.php\"); preg_match_all(\"/(?:use|require(?:_once)?\\s*\\(?)\\s*[\\\"\\\\']?([A-Za-z0-9_\\\\\\\\\\/\\\\.]+)/\", $s, $m); print implode(\" \", array_unique($m[1]));'); "
                "if [ -n \"$PKGS\" ]; then echo \"[atlas-runner] resolving composer packages\"; composer init --quiet --no-interaction --name=atlas/run >/dev/null 2>&1 || true; fi; "
                "php /tmp/app/main.php"
            ),
        ],
    ),
    "bash": LanguageSpec(
        image="bash:latest",
        filename="main.sh",
        command=["bash", "/work/main.sh"],
    ),
    "csharp": LanguageSpec(
        image="mcr.microsoft.com/dotnet/sdk:8.0",
        filename="Program.cs",
        command=[
            "sh",
            "-lc",
            "mkdir -p /tmp/app && cp /work/Program.cs /tmp/app/Program.cs && cd /tmp/app && dotnet new console --force -o . >/dev/null && cp /work/Program.cs ./Program.cs && dotnet run --nologo",
        ],
    ),
    "kotlin": LanguageSpec(
        image="zenika/kotlin:1.9-jdk17",
        filename="main.kts",
        command=["sh", "-lc", "cp /work/main.kts /tmp/main.kts && kotlinc -script /tmp/main.kts"],
    ),
    "swift": LanguageSpec(
        image="swift:5.9",
        filename="main.swift",
        command=["sh", "-lc", "cp /work/main.swift /tmp/main.swift && swift /tmp/main.swift"],
    ),
    "perl": LanguageSpec(
        image="perl:5",
        filename="main.pl",
        command=[
            "sh",
            "-lc",
            (
                "set -e; cp /work/main.pl /tmp/main.pl; "
                "MODS=$(grep -Eo '^\\s*use\\s+[A-Za-z0-9_:]+' /tmp/main.pl | awk '{print $2}' | grep -Ev '^(strict|warnings|utf8|lib|feature|constant|vars|parent|base|overload|Exporter|Carp)$' | sort -u || true); "
                "if [ -n \"$MODS\" ]; then echo \"[atlas-runner] installing: $MODS\"; cpanm --quiet --notest $MODS >/dev/null 2>&1 || true; fi; "
                "perl /tmp/main.pl"
            ),
        ],
    ),
    "lua": LanguageSpec(
        image="nickblah/lua:5.4-alpine",
        filename="main.lua",
        command=["lua", "/work/main.lua"],
    ),
    "r": LanguageSpec(
        image="r-base:latest",
        filename="main.R",
        command=[
            "sh",
            "-lc",
            (
                "set -e; cp /work/main.R /tmp/main.R; "
                "PKGS=$(grep -Eo '(library|require)\\([A-Za-z0-9._]+' /tmp/main.R | sed -E 's/(library|require)\\(//' | sort -u || true); "
                "if [ -n \"$PKGS\" ]; then echo \"[atlas-runner] installing: $PKGS\"; for p in $PKGS; do Rscript -e \"if(!require('$p',quietly=TRUE))install.packages('$p',repos='https://cloud.r-project.org')\" >/dev/null 2>&1 || true; done; fi; "
                "Rscript /tmp/main.R"
            ),
        ],
    ),
    "elixir": LanguageSpec(
        image="elixir:1.16-alpine",
        filename="main.exs",
        command=["elixir", "/work/main.exs"],
    ),
    "dart": LanguageSpec(
        image="dart:stable",
        filename="main.dart",
        command=[
            "sh",
            "-lc",
            (
                "set -e; mkdir -p /tmp/app/bin; cp /work/main.dart /tmp/app/bin/main.dart; cd /tmp/app; "
                "dart create -q -t console --force . >/dev/null 2>&1 || true; "
                "cp /work/main.dart bin/main.dart; "
                "PKGS=$(grep -Eo \"package:[A-Za-z0-9_]+\" bin/main.dart | sed 's/package://' | sort -u || true); "
                "if [ -n \"$PKGS\" ]; then echo \"[atlas-runner] installing: $PKGS\"; for p in $PKGS; do dart pub add $p >/dev/null 2>&1 || true; done; fi; "
                "dart run bin/main.dart"
            ),
        ],
    ),
}


LANGUAGE_ALIASES: dict[str, str] = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "node": "javascript",
    "ts": "typescript",
    "golang": "go",
    "rs": "rust",
    "c++": "cpp",
    "cxx": "cpp",
    "cc": "cpp",
    "rb": "ruby",
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "cs": "csharp",
    "c#": "csharp",
    "kt": "kotlin",
    "kts": "kotlin",
    "pl": "perl",
    "ex": "elixir",
    "exs": "elixir",
}


CLIENT_LANGUAGES = {"html", "htm"}


def resolve_language(language: str) -> str | None:
    normalized = (language or "").strip().lower()
    if not normalized:
        return None
    if normalized in LANGUAGES:
        return normalized
    if normalized in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[normalized]
    return None


def supported_languages() -> list[str]:
    return sorted(set(LANGUAGES.keys()) | set(LANGUAGE_ALIASES.keys()) | CLIENT_LANGUAGES)


def _docker_binary() -> str | None:
    return shutil.which("docker")


_image_build_lock = threading.Lock()


def _image_exists(image: str) -> bool:
    binary = _docker_binary()
    if not binary:
        return False
    try:
        completed = subprocess.run(
            [binary, "image", "inspect", image],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _ensure_python_gui_image(
    progress: "Any | None" = None,
) -> None:
    if _image_exists(PYTHON_GUI_IMAGE):
        return
    with _image_build_lock:
        if _image_exists(PYTHON_GUI_IMAGE):
            return
        dockerfile = Path(__file__).parent / "runner_images" / "python_gui.Dockerfile"
        if not dockerfile.exists():
            raise RuntimeError(f"Runner image Dockerfile missing: {dockerfile}")
        binary = _docker_binary()
        if not binary:
            raise RuntimeError("Docker CLI is unavailable while building the GUI runner image.")
        if progress is not None:
            progress("[atlas-runner] Building GUI runner image (one-time, ~1-3 min)…\n")
        process = subprocess.Popen(
            [
                binary,
                "build",
                "-t",
                PYTHON_GUI_IMAGE,
                "-f",
                str(dockerfile),
                str(dockerfile.parent),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        last_line = ""
        assert process.stdout is not None
        for line in process.stdout:
            last_line = line.rstrip() or last_line
            if progress is not None:
                progress(line)
        code_ = process.wait()
        if code_ != 0:
            raise RuntimeError(
                f"Failed to build the Python GUI runner image: {last_line or 'see docker output'}"
            )
        if progress is not None:
            progress("[atlas-runner] GUI runner image ready.\n")


def _python_gui_plan(code: str) -> RunPlan:
    novnc_host_port = _reserve_host_port()
    install_script = (
        "set -e; cp /work/main.py /tmp/main.py; cd /tmp; "
        "PY_IMPORTS=$(python - <<'PY'\n"
        "import ast, sys\n"
        "STDLIB = set(sys.stdlib_module_names)\n"
        "ALIAS = {'cv2':'opencv-python','sklearn':'scikit-learn','PIL':'Pillow','bs4':'beautifulsoup4','yaml':'PyYAML','skimage':'scikit-image'}\n"
        "src = open('/tmp/main.py').read()\n"
        "try:\n"
        "    tree = ast.parse(src)\n"
        "except SyntaxError:\n"
        "    sys.exit(0)\n"
        "pkgs = set()\n"
        "for node in ast.walk(tree):\n"
        "    if isinstance(node, ast.Import):\n"
        "        for n in node.names:\n"
        "            pkgs.add(n.name.split('.')[0])\n"
        "    elif isinstance(node, ast.ImportFrom):\n"
        "        if node.module and node.level == 0:\n"
        "            pkgs.add(node.module.split('.')[0])\n"
        "needed = sorted({ALIAS.get(p, p) for p in pkgs if p and p not in STDLIB})\n"
        "print(' '.join(needed))\n"
        "PY\n"
        "); "
        "if [ -n \"$PY_IMPORTS\" ]; then echo \"[atlas-runner] installing: $PY_IMPORTS\"; pip install --quiet --no-input --disable-pip-version-check --root-user-action=ignore $PY_IMPORTS || true; fi; "
        "echo \"[atlas-runner] GUI ready on port 6080\"; "
        "python -u /tmp/main.py"
    )
    return RunPlan(
        image=PYTHON_GUI_IMAGE,
        filename="main.py",
        command=["sh", "-lc", install_script],
        ports={novnc_host_port: NOVNC_CONTAINER_PORT},
        gui=True,
    )


def resolve_plan(language: str, code: str, progress: "Any | None" = None) -> RunPlan:
    if language == "python" and _python_gui_detected(code):
        if not _image_exists(PYTHON_GUI_IMAGE):
            raise RuntimeError(
                "Atlas needs to build a GUI runner image the first time you run "
                "a graphical Python program. Run the CLI command "
                "'atlas-build-gui-image' or restart the app — the build takes "
                "1-3 minutes. (Missing image: "
                f"{PYTHON_GUI_IMAGE})"
            )
        return _python_gui_plan(code)
    spec = LANGUAGES[language]
    return RunPlan(image=spec.image, filename=spec.filename, command=list(spec.command))


def docker_status() -> dict[str, Any]:
    binary = _docker_binary()
    if not binary:
        return {
            "available": False,
            "reason": "Docker CLI was not found on PATH. Install Docker Desktop and try again.",
        }
    try:
        completed = subprocess.run(
            [binary, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "Docker is installed but the daemon did not respond in time."}
    except OSError as exc:
        return {"available": False, "reason": f"Failed to invoke docker: {exc}"}

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        reason = "Docker Desktop is installed but not running. Start Docker Desktop and try again."
        if detail:
            reason = f"{reason} Details: {detail.splitlines()[-1]}"
        return {"available": False, "reason": reason}
    version = completed.stdout.strip() or "unknown"
    return {"available": True, "server_version": version}


@dataclass
class RunnerProcess:
    run_id: str
    language: str
    container_name: str
    work_dir: Path
    started_at: float
    process: subprocess.Popen
    events: queue.Queue = field(default_factory=queue.Queue)
    history: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    finished: bool = False
    exit_code: int | None = None
    subscribers: list[queue.Queue] = field(default_factory=list)


class CodeRunner:
    def __init__(self) -> None:
        self._runs: dict[str, RunnerProcess] = {}
        self._lock = threading.Lock()

    def start(self, language: str, code: str) -> dict[str, Any]:
        resolved = resolve_language(language)
        if not resolved:
            raise RuntimeError(f"Language '{language}' is not supported.")
        if resolved in CLIENT_LANGUAGES:
            raise RuntimeError("HTML is rendered in the client sandbox, not via Docker.")

        binary = _docker_binary()
        if not binary:
            raise RuntimeError("Docker CLI was not found on PATH.")

        plan = resolve_plan(resolved, code)
        run_id = uuid.uuid4().hex[:16]
        container_name = f"atlas-run-{run_id}"
        work_dir = Path(tempfile.mkdtemp(prefix=f"atlas-run-{run_id}-"))
        source_path = work_dir / plan.filename
        source_path.write_text(code, encoding="utf-8")

        docker_args: list[str] = [
            binary,
            "run",
            "--rm",
            "-i",
            "--name",
            container_name,
            "--memory",
            "2g",
            "--cpus",
            "2",
            "--pids-limit",
            "512",
            "-v",
            f"{work_dir}:/work:ro",
            "-w",
            "/work",
        ]
        for host_port, container_port in plan.ports.items():
            docker_args.extend(["-p", f"127.0.0.1:{host_port}:{container_port}"])
        docker_args.append(plan.image)
        docker_args.extend(plan.command)

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = 0x08000000  # CREATE_NO_WINDOW

        try:
            process = subprocess.Popen(
                docker_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags if sys.platform == "win32" else 0,
            )
        except OSError as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise RuntimeError(f"Failed to start Docker: {exc}") from exc

        runner = RunnerProcess(
            run_id=run_id,
            language=resolved,
            container_name=container_name,
            work_dir=work_dir,
            started_at=time.time(),
            process=process,
        )
        with self._lock:
            self._runs[run_id] = runner

        threading.Thread(target=self._pump_stream, args=(runner, process.stdout, "stdout"), daemon=True).start()
        threading.Thread(target=self._pump_stream, args=(runner, process.stderr, "stderr"), daemon=True).start()
        threading.Thread(target=self._wait_for_exit, args=(runner,), daemon=True).start()

        response: dict[str, Any] = {"run_id": run_id, "language": resolved, "container": container_name}
        if plan.gui:
            host_port = next(iter(plan.ports.keys()))
            response["vnc_url"] = (
                f"http://127.0.0.1:{host_port}/vnc.html?autoconnect=1&resize=remote&reconnect=1"
            )
        return response

    def subscribe(self, run_id: str) -> tuple[list[dict[str, Any]], queue.Queue, bool]:
        runner = self._require(run_id)
        with runner.lock:
            history = list(runner.history)
            if runner.finished:
                return history, queue.Queue(), True
            subscriber: queue.Queue = queue.Queue()
            runner.subscribers.append(subscriber)
            return history, subscriber, False

    def unsubscribe(self, run_id: str, subscriber: queue.Queue) -> None:
        runner = self._runs.get(run_id)
        if not runner:
            return
        with runner.lock:
            if subscriber in runner.subscribers:
                runner.subscribers.remove(subscriber)

    def stop(self, run_id: str) -> dict[str, Any]:
        runner = self._runs.get(run_id)
        if not runner:
            return {"run_id": run_id, "status": "unknown"}
        binary = _docker_binary()
        if binary:
            try:
                subprocess.run(
                    [binary, "kill", runner.container_name],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            runner.process.kill()
        except OSError:
            pass
        return {"run_id": run_id, "status": "stopping"}

    def _require(self, run_id: str) -> RunnerProcess:
        runner = self._runs.get(run_id)
        if not runner:
            raise RuntimeError(f"Runner '{run_id}' is not known.")
        return runner

    def _emit(self, runner: RunnerProcess, event: dict[str, Any]) -> None:
        with runner.lock:
            runner.history.append(event)
            subscribers = list(runner.subscribers)
        for subscriber in subscribers:
            subscriber.put(event)

    def _pump_stream(self, runner: RunnerProcess, stream: Iterable[str] | None, channel: str) -> None:
        if stream is None:
            return
        try:
            for line in stream:
                if line is None:
                    break
                self._emit(runner, {"type": "output", "stream": channel, "chunk": line})
        except Exception as exc:  # pragma: no cover - defensive
            self._emit(runner, {"type": "output", "stream": "stderr", "chunk": f"[atlas-runner] stream error: {exc}\n"})

    def _wait_for_exit(self, runner: RunnerProcess) -> None:
        try:
            exit_code = runner.process.wait()
        except Exception as exc:  # pragma: no cover - defensive
            exit_code = -1
            self._emit(runner, {"type": "output", "stream": "stderr", "chunk": f"[atlas-runner] wait error: {exc}\n"})
        duration_ms = int((time.time() - runner.started_at) * 1000)
        event = {
            "type": "exit",
            "code": exit_code,
            "duration_ms": duration_ms,
        }
        with runner.lock:
            runner.finished = True
            runner.exit_code = exit_code
            runner.history.append(event)
            subscribers = list(runner.subscribers)
            runner.subscribers.clear()
        for subscriber in subscribers:
            subscriber.put(event)
        shutil.rmtree(runner.work_dir, ignore_errors=True)


_runner_singleton: CodeRunner | None = None
_runner_lock = threading.Lock()


def get_runner() -> CodeRunner:
    global _runner_singleton
    with _runner_lock:
        if _runner_singleton is None:
            _runner_singleton = CodeRunner()
        return _runner_singleton
