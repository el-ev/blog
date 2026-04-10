from argparse import Namespace

from .content import update_content


def run_update(args: Namespace) -> None:
    update_content(args)
