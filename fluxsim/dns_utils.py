import os, re, time
from typing import List
from .config import DNS_ZONE_FILE_PATH_TEMPLATE, FLUX_IPS_FILE_PATH_TEMPLATE

SERIAL_LINE = r"^\s*(\d+)\s*; Serial \(dynamically generated\)\s*$"

def write_zone_file(network_name: str, dns_ip: str, domain: str, subnet_octet: int, ttl: int) -> str:
    serial = time.strftime("%Y%m%d") + "01"
    zone_root = "sim.local."
    label = network_name
    initial_ip = f"172.{subnet_octet}.0.5"
    content = f"""$TTL {ttl}
$ORIGIN {zone_root}
@       IN SOA  ns.sim.local. root.sim.local. (
                 {serial} ; Serial (dynamically generated)
                 30M
                 15M
                 1W
                 1M )
@       IN NS   ns.sim.local.
ns      IN A {dns_ip}

{label} IN A {initial_ip}
"""
    os.makedirs("dns_config", exist_ok=True)
    path = DNS_ZONE_FILE_PATH_TEMPLATE.format(network_name=network_name)
    with open(path,"w") as f: f.write(content)
    return path

def bump_serial(zone: str) -> str:
    m = re.search(SERIAL_LINE, zone, flags=re.M)
    if m:
        cur = int(m.group(1)); serial = str(cur + 1)
        return re.sub(SERIAL_LINE, f"                 {serial} ; Serial (dynamically generated)", zone, flags=re.M)
    else:
        return zone

def set_single_a_record(path: str, label: str, ip: str):
    with open(path,"r") as f: zone = f.read()
    zone = bump_serial(zone)
    label_pat = rf"^[ \t]*{re.escape(label)}[ \t]+IN[ \t]+A[ \t]+[0-9.]+"
    if re.search(label_pat, zone, flags=re.M):
        zone = re.sub(label_pat, f"{label}  IN A {ip}", zone, flags=re.M)
    else:
        zone += ("" if zone.endswith("\n") else "\n") + f"{label}  IN A {ip}\n"
    with open(path,"w") as f: f.write(zone)

def set_multi_a_records(path: str, label: str, ips: List[str]):
    with open(path,"r") as f: zone = f.read()
    zone = bump_serial(zone)
    block = "\n".join([f"{label}  IN A {ip}" for ip in ips])
    zone = re.sub(rf"^[ \t]*{re.escape(label)}[ \t]+IN[ \t]+A[ \t]+[0-9.]+.*\n?", "", zone, flags=re.M)
    zone += ("" if zone.endswith("\n") else "\n") + block + "\n"
    with open(path,"w") as f: f.write(zone)

def write_flux_agents(network_name: str, ips: List[str]):
    """
    Ensure dns_config/flux_agents_<net>.txt is a regular file.
    If a directory exists at that path (accidentally created), move it aside.
    """
    path = FLUX_IPS_FILE_PATH_TEMPLATE.format(network_name=network_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # If a directory sits at the target path, move it out of the way (non-destructive).
    if os.path.isdir(path):
        backup = f"{path}.backup_{int(time.time())}"
        try:
            os.rename(path, backup)
        except Exception as e:
            raise IOError(
                f"Cannot prepare flux agents file. A directory exists at '{path}' "
                f"and could not be moved aside: {e}"
            )

    with open(path, "w") as f:
        f.write("\n".join(ips) + ("\n" if ips else ""))
    return path

def set_zone_ttl(path: str, ttl: int):
    """
    Update the $TTL directive at the top of the given zone file.
    Bumps the serial so running BIND instances can notice the change.
    """
    with open(path, "r") as f:
        zone = f.read()

    lines = zone.splitlines()
    updated = False
    for idx, line in enumerate(lines):
        if line.strip().startswith("$TTL"):
            lines[idx] = f"$TTL {ttl}"
            updated = True
            break

    if not updated:
        lines.insert(0, f"$TTL {ttl}")

    new_zone_body = "\n".join(lines)
    if not new_zone_body.endswith("\n"):
        new_zone_body += "\n"
    new_zone = bump_serial(new_zone_body)
    with open(path, "w") as f:
        f.write(new_zone)
