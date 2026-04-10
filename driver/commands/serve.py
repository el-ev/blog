import os
import subprocess
import sys
from argparse import Namespace


def run_serve(args: Namespace) -> None:
    root_dir: str = args.root_dir
    if not os.path.isdir(root_dir):
        print(f"Directory '{root_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    port: int = args.port
    if port < 1 or port > 65535:
        print("Port must be between 1 and 65535.", file=sys.stderr)
        sys.exit(1)

    bind: str = args.bind
    print(f"Serving '{root_dir}' at http://{bind}:{port}/ (Ctrl+C to stop)")

    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "http.server",
                str(port),
                "--bind",
                bind,
                "--directory",
                root_dir,
            ],
            check=True,
        )
    except KeyboardInterrupt:
        print("\nServer stopped.")
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
