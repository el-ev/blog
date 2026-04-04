import os
import sys
import shutil
from argparse import Namespace

def run_init(args: Namespace) -> None:
    workspace_base: str = args.workspace_base
    os.makedirs(workspace_base, exist_ok=True)
    template_dir: str = args.template_dir
    
    if not os.path.exists(template_dir):
        print(f"Template directory '{template_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    workspace_name: str = args.name[0]
    workspace_path = os.path.join(workspace_base, workspace_name)
    
    if os.path.exists(workspace_path):
        print(f"Workspace '{workspace_name}' already exists.", file=sys.stderr)
        sys.exit(1)
        
    shutil.copytree(template_dir, workspace_path)
    print(f"Workspace created at {workspace_path}")