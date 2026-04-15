import argparse
import os
from argparse import ArgumentParser, BooleanOptionalAction, Namespace

from commands.init import run_init
from commands.compile import run_compile
from commands.submit import run_submit, run_amend_all
from commands.content import update_content
from commands.upload import run_upload
from commands.recover import run_recover
from commands.serve import run_serve
from commands.utils import validate_workspace_name


def _parse_workspace_name(value: str) -> str:
    try:
        return validate_workspace_name(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def _add_command_parsers(subparsers: argparse._SubParsersAction) -> None:
    init_parser = subparsers.add_parser(
        "init",
        help="Create a new post draft with the specified workspace name.",
    )
    init_parser.add_argument("name", type=_parse_workspace_name)

    compile_parser = subparsers.add_parser(
        "compile",
        help="Name of the workspace to be compiled.",
    )
    compile_parser.add_argument("name", type=_parse_workspace_name)
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
    submit_parser.add_argument("name", type=_parse_workspace_name)
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
        type=_parse_workspace_name,
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
    _add_command_parsers(subparsers)

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
    command_handlers[str(args.command)](args)


if __name__ == "__main__":
    main()
