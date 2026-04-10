import os
import sys
import shutil
from argparse import Namespace

from .utils import (
    WORKSPACE_PUBLIC_DIR_NAME,
    safe_join_child,
)

def run_init(args: Namespace) -> None:
    workspace_base: str = args.workspace_base
    os.makedirs(workspace_base, exist_ok=True)
    template_dir: str = args.template_dir
    
    if not os.path.exists(template_dir):
        print(f"Template directory '{template_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    workspace_name: str = args.name

    workspace_path = safe_join_child(workspace_base, workspace_name)
    
    if os.path.exists(workspace_path):
        print(f"Workspace '{workspace_name}' already exists.", file=sys.stderr)
        sys.exit(1)
        
    shutil.copytree(template_dir, workspace_path)
    os.makedirs(os.path.join(workspace_path, WORKSPACE_PUBLIC_DIR_NAME), exist_ok=True)
    print(f"Workspace created at {workspace_path}")
