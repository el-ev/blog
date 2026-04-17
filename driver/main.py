import argparse
import json
import os
import sys
from argparse import ArgumentParser, BooleanOptionalAction, Namespace
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

try:
    import fcntl  # type: ignore
except ImportError:
    fcntl = None

from commands.init import run_init
from commands.compile import run_compile
from commands.submit import run_submit, run_amend_all
from commands.content import update_content
from commands.upload import run_upload
from commands.recover import run_recover
from commands.serve import run_serve
from commands.utils import validate_workspace

_DRIVER_LOCK_FILENAME = ".driver.lock"
_MUTATING_COMMANDS = {
    "init",
    "compile",
    "submit",
    "amend-all",
    "recover",
    "update",
    "upload",
}


def _lock_path(args: Namespace) -> str:
    paths = [
        os.path.abspath(str(args.workspace_base)),
        os.path.abspath(str(args.build_base)),
        os.path.abspath(str(args.root_dir)),
    ]
    try:
        lock_base = os.path.commonpath(paths)
    except ValueError:
        lock_base = os.getcwd()
    if lock_base == os.path.sep:
        lock_base = os.getcwd()
    return os.path.join(lock_base, _DRIVER_LOCK_FILENAME)


def _read_lock_info(lock_path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(lock_path):
        return None

    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except OSError:
        return None
    if not content:
        return None

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _lock_holder(lock_info: Optional[Dict[str, Any]]) -> str:
    if not lock_info:
        return "another process"

    pid_raw = lock_info.get("pid")
    cmd_raw = lock_info.get("command")
    if isinstance(pid_raw, int) and isinstance(cmd_raw, str) and cmd_raw:
        return f"pid {pid_raw} ({cmd_raw})"
    if isinstance(pid_raw, int):
        return f"pid {pid_raw}"
    return "another process"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@contextmanager
def _mutating_cmd_lock(args: Namespace, command: str) -> Iterator[None]:
    lock_path = _lock_path(args)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock_payload = {"pid": os.getpid(), "command": command}

    if fcntl is not None:
        with open(lock_path, "a+", encoding="utf-8") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                holder = _lock_holder(_read_lock_info(lock_path))
                print(
                    f"Cannot run '{command}': driver lock is held by {holder}.",
                    file=sys.stderr,
                )
                sys.exit(1)

            f.seek(0)
            f.truncate()
            json.dump(lock_payload, f, ensure_ascii=False)
            f.write("\n")
            f.flush()
            try:
                yield
            finally:
                f.seek(0)
                f.truncate()
                f.flush()
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            lock_info = _read_lock_info(lock_path)
            pid_raw = lock_info.get("pid") if lock_info else None
            stale_lock = isinstance(pid_raw, int) and not _pid_alive(pid_raw)
            if stale_lock:
                try:
                    os.remove(lock_path)
                    continue
                except OSError:
                    pass
            holder = _lock_holder(lock_info)
            print(
                f"Cannot run '{command}': driver lock is held by {holder}.",
                file=sys.stderr,
            )
            sys.exit(1)

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(lock_payload, f, ensure_ascii=False)
            f.write("\n")
        break

    try:
        yield
    finally:
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass


def _parse_name(value: str) -> str:
    try:
        return validate_workspace(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def _add_cmds(subparsers: argparse._SubParsersAction) -> None:
    init_parser = subparsers.add_parser(
        "init",
        help="Create a new post draft with the specified workspace name.",
    )
    init_parser.add_argument("name", type=_parse_name)

    compile_parser = subparsers.add_parser(
        "compile",
        help="Name of the workspace to be compiled.",
    )
    compile_parser.add_argument("name", type=_parse_name)
    compile_parser.add_argument(
        "--amend",
        action=BooleanOptionalAction,
        help="If set, compile with amend metadata for latest-revision links.",
        default=False,
        dest="amend",
    )

    submit_parser = subparsers.add_parser(
        "submit",
        help="Name of the workspace to be submitted.",
    )
    submit_parser.add_argument("name", type=_parse_name)
    submit_parser.add_argument(
        "--amend",
        action=BooleanOptionalAction,
        help="If set, the blog post will replace the latest revision instead of creating a new one.",
        default=False,
        dest="amend",
    )
    subparsers.add_parser(
        "amend-all",
        help="Amend the latest published revision of every workspace using its bundled source snapshot.",
    )

    recover_parser = subparsers.add_parser(
        "recover",
        help="Name of the workspace to recover from the latest post source snapshot.",
    )
    recover_parser.add_argument(
        "name",
        type=_parse_name,
    )
    recover_parser.add_argument(
        "--force",
        action=BooleanOptionalAction,
        default=False,
        help="If set, remove an existing local workspace before recovery.",
        dest="force",
    )

    subparsers.add_parser(
        "update",
        help="Update the content page, sitemap, and RSS feed.",
    )
    upload_parser = subparsers.add_parser(
        "upload", help="Upload the generated root directory to Google Cloud Storage"
    )
    upload_parser.add_argument(
        "--bucket",
        required=False,
        help="Name of the GCS bucket to upload the content to. Overrides config.",
    )
    upload_parser.add_argument(
        "--prefix",
        default=None,
        help="Prefix (folder) under which to upload the files in GCS (default: blog/). Overrides config.",
    )
    upload_parser.add_argument(
        "--project",
        default=None,
        help="The Google Cloud project ID (optional if implicitly configured). Overrides config.",
    )
    serve_parser = subparsers.add_parser(
        "serve",
        help="Serve the generated root directory over HTTP.",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for the local HTTP server (default: 8000).",
    )
    serve_parser.add_argument(
        "--bind",
        default="127.0.0.1",
        help="Bind address for the local HTTP server (default: 127.0.0.1).",
    )


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="Blog Driver",
        description="Driver for building blog posts from Typst sources.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_cmds(subparsers)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    current_cwd = os.getcwd()

    parser.add_argument("--template-dir", default=os.path.join(base_dir, "template"))
    parser.add_argument(
        "--workspace-base", default=os.path.join(current_cwd, "workspace")
    )
    parser.add_argument("--build-base", default=os.path.join(current_cwd, "build"))
    parser.add_argument("--root-dir", default=os.path.join(current_cwd, "root"))
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL for the sitemap and RSS feed. Overrides config.",
    )
    parser.add_argument(
        "--config",
        default=os.path.join(current_cwd, "config.json"),
        help="Path to a JSON config file.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args: Namespace = parser.parse_args()

    command_handlers = {
        "init": run_init,
        "compile": run_compile,
        "submit": run_submit,
        "amend-all": run_amend_all,
        "recover": run_recover,
        "update": update_content,
        "upload": run_upload,
        "serve": run_serve,
    }
    command = str(args.command)
    handler = command_handlers[command]
    if command in _MUTATING_COMMANDS:
        with _mutating_cmd_lock(args, command):
            handler(args)
    else:
        handler(args)


if __name__ == "__main__":
    main()
