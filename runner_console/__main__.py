import argparse
import json
import os
from pathlib import Path
import sys
from . import __version__, common


def main():
    parser = argparse.ArgumentParser(description="Local console for an existing GitHub Actions runner.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, help="JSON configuration file")
    parser.add_argument("--runner-dir", type=Path, help="Existing actions-runner directory")
    parser.add_argument("--data-dir", type=Path, help="Private dashboard state and rotating logs")
    parser.add_argument("--title", help="Display title")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show", help="Open the interactive dashboard")
    commands.add_parser("collect", help="Collect masked job output in the background")
    hook = commands.add_parser("hook", help="Called by the runner's job hooks")
    hook.add_argument("phase", choices=["started", "completed"])
    install = commands.add_parser("install-hooks", help="Install hooks; restart the runner when idle afterward")
    install.add_argument("--replace-hooks", action="store_true")
    commands.add_parser("uninstall-hooks", help="Restore only the hooks installed by this tool")
    commands.add_parser("status", help="Print current telemetry as JSON")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig")) if args.config else {}
        runner = args.runner_dir or config.get("runner_dir")
        if not runner:
            parser.error("--runner-dir or runner_dir in --config is required")
        runner = Path(runner).expanduser().resolve()
        if not (runner / "_diag").is_dir():
            parser.error("runner directory must contain _diag (start/configure the GitHub runner first)")
        default_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ActionsRunnerConsole"
        if os.name != "nt":
            default_data = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "actions-runner-console"
        data = Path(args.data_dir or config.get("data_dir") or default_data).expanduser().resolve()
        common.configure(runner, data, args.title or config.get("title", "Actions Runner Console"))
        if args.command == "show":
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                parser.error("show requires an interactive terminal; use collect or status for background use")
            if os.name == "nt":
                from .windows import display
                display()
            else:
                import curses
                from .linux import display
                curses.wrapper(display)
        elif args.command == "collect":
            from .lock import CollectorLock
            with CollectorLock(data):
                common.collect()
        elif args.command == "hook":
            common.hook(args.phase)
        elif args.command in ("install-hooks", "uninstall-hooks"):
            from . import hooks
            if args.command == "install-hooks":
                if not args.config:
                    parser.error("install-hooks requires a persistent --config")
                hooks.install(runner, data, args.config.resolve(), args.replace_hooks)
            else:
                hooks.uninstall(runner, data)
        else:
            print(json.dumps(common.read_json("status.json"), indent=2))
    except KeyboardInterrupt:
        return
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"runner-console: {exc}\n")


if __name__ == "__main__":
    main()
