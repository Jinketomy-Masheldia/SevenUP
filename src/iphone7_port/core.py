"""Private state, checked subprocesses, and immutable artifact publication."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import shlex
from datetime import datetime, timezone
from pathlib import Path
from .console import paint
from .process import live_run


class PortError(Exception):
    """An actionable failure that must stop the current stage."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PortError(message)


def command_display(command, private):
    name = Path(command[0]).name
    if not private:
        return shlex.join(command)
    if name == 'sshpass' and '-e' in command:
        if 'scp' in command:
            return f'scp {command[-2]} -> {command[-1]}'
        if 'ssh' in command and 'root@127.0.0.1' in command:
            index = command.index('root@127.0.0.1')
            return 'ssh: ' + ' '.join(command[index + 1:])
    if name == 'scp':
        return f'scp {command[-2]} -> {command[-1]}'
    if name == 'irecovery':
        args = list(command[1:])
        if '-i' in args and args.index('-i') + 1 < len(args):
            args[args.index('-i') + 1] = '<device>'
        return shlex.join([name, *args])
    if name == 'gaster':
        return shlex.join([name, *command[1:2]])
    return name


def digest_file(path: Path, algorithms=("md5", "sha1", "sha256")) -> dict:
    hashes = {name: hashlib.new(name) for name in algorithms}
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            for hasher in hashes.values():
                hasher.update(chunk)
    return {name: hasher.hexdigest() for name, hasher in hashes.items()}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_json(path: Path, default=None):
    if not path.exists() and default is not None:
        return default
    return json.loads(path.read_text())


class Project:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.work = self.root / "work"
        self.output = self.root / "output"
        self.profile = load_json(self.root / "profiles/d10-20b82.json")
        self.sources = load_json(self.root / "profiles/sources.lock.json")["sources"]
        # Configuration is fixed by the bundled profiles. Legacy local.json
        # files are deliberately not read.

    def initialize(self):
        for path in [self.work, self.output, self.root / "logs"]:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)

    def read_state(self) -> dict:
        return load_json(self.work / "state.json", {"schema": 1, "stages": {}})

    def record(self, stage: str, result: dict):
        state = self.read_state()
        state["stages"][stage] = {"at": utc_now(), **result}
        save_json(self.work / "state.json", state)

    def stage(self, name: str) -> dict:
        state = self.read_state()["stages"]
        require(name in state, f"Stage '{name}' has not completed.")
        return state[name]

    def tool(self, name: str) -> str:
        from .dependencies import dependency
        fetched = dependency(self, 'Darwin/' + name)
        if fetched is not None:
            return str(fetched)
        candidate = self.root / 'Darwin' / name
        if candidate.exists():
            require(candidate.is_file() and os.access(candidate, os.X_OK), f"Tool is not executable: {candidate}")
            # Preserve the executable name: ld64.lld selects its mode from argv[0].
            return str(candidate.absolute())
        found = shutil.which(name)
        require(bool(found), f"Missing tool '{name}'. Restore the bundled Darwin/ directory or install it in PATH.")
        return found

    def linker(self) -> str:
        bundled = self.root / 'Darwin/ld64.lld'
        if bundled.exists():
            require(bundled.is_file() and os.access(bundled, os.X_OK), f'Linker is not executable: {bundled}')
            from .host_runtime import prepare_linker
            prepare_linker(self)
            return str(bundled.absolute())
        found = shutil.which('ld64.lld')
        require(bool(found), 'Missing ld64.lld. Restore the bundled Darwin/ directory or install it in PATH.')
        return found

    def run(self, arguments, *, timeout=180, private=False, env=None, cwd=None, input=None, label=None, live=False) -> subprocess.CompletedProcess:
        self.initialize()
        # Device identities, passwords, nonces, and raw command output stay local.
        command = [str(item) for item in arguments]
        display = label or command_display(command, private)
        print(f"{paint('Running:')} {display}", flush=True)
        try:
            if live:
                result = live_run(command, timeout=timeout, env=env, cwd=cwd, input=input)
            else:
                result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=timeout, env=env, cwd=cwd, input=input)
        except (OSError, subprocess.SubprocessError) as exc:
            save_json(self.root / "logs/last-command.json", {
                "at": utc_now(), "command": [Path(command[0]).name] if private else command,
                "error": type(exc).__name__, "timeout": timeout, "action": display,
            })
            raise PortError(f"Command failed or timed out: {display}. {type(exc).__name__}") from exc
        report = {"at": utc_now(), "command": [Path(command[0]).name] if private else command, "action": display,
                  "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        if input is not None:
            report['script'] = input
        log_fd, log_name = tempfile.mkstemp(prefix="command-", suffix=".json", dir=self.root / "logs")
        os.close(log_fd)
        save_json(Path(log_name), report)
        save_json(self.root / "logs/last-command.json", report)
        if result.returncode:
            suffix = ' See logs/last-command.json (private).'
            if not live:
                suffix += '\n' + (result.stderr or result.stdout)[-2000:]
            raise PortError(f"Command returned {result.returncode}: {display}.{suffix}")
        return result


def publish_directory(staging: Path, destination: Path):
    require(not destination.exists(), f"Output already exists: {destination}. Keep it or explicitly move it aside.")
    os.replace(staging, destination)
