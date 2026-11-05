"""Install reversible job hooks without discarding other runner environment settings."""
import json
import os
from pathlib import Path
import shlex
import sys

KEYS = ("ACTIONS_RUNNER_HOOK_JOB_STARTED", "ACTIONS_RUNNER_HOOK_JOB_COMPLETED")


def install(runner, data, config, replace=False):
    launcher = Path(__file__).resolve().parent.parent / "run.py"
    env = runner / ".env"
    lines = env.read_text(encoding="utf-8-sig").splitlines() if env.exists() else []
    original = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key in KEYS:
            original[key] = value
    suffix = ".ps1" if os.name == "nt" else ".sh"
    targets = {key: str(launcher.parent / ("job-" + phase + suffix))
               for key, phase in zip(KEYS, ("started", "completed"))}
    conflict = [key for key in KEYS if key in original and original[key] != targets[key]]
    if conflict and not replace:
        raise RuntimeError("Existing runner hooks detected. Chain them manually or explicitly use --replace-hooks.")
    backup = data / "hooks-before.json"
    if not backup.exists():
        backup.write_text(json.dumps(original), encoding="utf-8")
        if os.name != "nt":
            backup.chmod(0o600)
    for key, phase in zip(KEYS, ("started", "completed")):
        arguments = [sys.executable, str(launcher), "--config", str(config), "hook", phase]
        target = Path(targets[key])
        if os.name == "nt":
            quote = lambda value: "'" + value.replace("'", "''") + "'"
            content = "& " + " ".join(quote(value) for value in arguments) + "\nexit $LASTEXITCODE\n"
        else:
            content = "#!/bin/sh\nexec " + shlex.join(arguments) + "\n"
        target.write_text(content, encoding="utf-8", newline="\n")
        if os.name != "nt":
            target.chmod(0o755)
    updated = [line for line in lines if line.partition("=")[0] not in KEYS]
    updated.extend(key + "=" + targets[key] for key in KEYS)
    env.write_text("\n".join(updated) + "\n", encoding="utf-8")


def uninstall(runner, data):
    env = runner / ".env"
    backup = data / "hooks-before.json"
    if not env.exists() or not backup.exists():
        return
    original = json.loads(backup.read_text(encoding="utf-8"))
    own = Path(__file__).resolve().parent.parent
    updated = []
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.partition("=")
        if separator and key in KEYS and Path(value).parent == own and Path(value).name in (
                "job-started.sh", "job-completed.sh", "job-started.ps1", "job-completed.ps1"):
            if key in original:
                updated.append(key + "=" + original[key])
        else:
            updated.append(line)
    env.write_text("\n".join(updated) + "\n", encoding="utf-8")
