import re, subprocess
from typing import List, Optional
from .config import PROJECT_NAME

def compose(args: list[str], compose_file: str, check: bool = True) -> Optional[str]:
    cmd = ["docker","compose","-p",PROJECT_NAME,"-f",compose_file] + args
    try:
        res = subprocess.run(cmd, check=check, capture_output=True, text=True)
        return res.stdout.strip() if check else res
    except subprocess.CalledProcessError as e:
        print(f"[compose error] {e.stderr.strip()}")
        return None

def service_container_ids(service: str, compose_file: str) -> List[str]:
    try:
        p = subprocess.run(
            ["docker","compose","-p",PROJECT_NAME,"-f",compose_file,"ps","-q",service],
            check=True, capture_output=True, text=True
        )
        return [i for i in p.stdout.splitlines() if i.strip()]
    except subprocess.CalledProcessError:
        return []

def container_ip_on_net(container_id: str, project_net: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["docker","inspect","-f", f'{{{{ (index .NetworkSettings.Networks "{project_net}").IPAddress }}}}', container_id],
            check=True, capture_output=True, text=True
        ).stdout.strip()
        return out if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", out or "") else None
    except subprocess.CalledProcessError:
        return None
