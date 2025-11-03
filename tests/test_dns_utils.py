import os
import re
from pathlib import Path

import pytest

from fluxsim import dns_utils


def _read(path: Path) -> str:
    return path.read_text()


@pytest.fixture(autouse=True)
def temp_cwd(tmp_path, monkeypatch):
    """Ensure filesystem operations under fluxsim.dns_utils stay isolated."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_write_zone_file_creates_expected_content():
    zone_path = Path(
        dns_utils.write_zone_file(
            network_name="fluxy",
            dns_ip="172.60.0.53",
            domain="fluxy.sim.local",
            subnet_octet=60,
            ttl=120,
        )
    )
    assert zone_path.exists()
    body = _read(zone_path)
    assert body.startswith("$TTL 120")
    assert "ns      IN A 172.60.0.53" in body
    assert "fluxy IN A 172.60.0.5" in body


def test_set_single_a_record_updates_existing_entry():
    path = Path(
        dns_utils.write_zone_file("demo", "172.60.0.53", "demo.sim.local", 60, 60)
    )
    original = _read(path)
    original_serial = re.search(dns_utils.SERIAL_LINE, original, flags=re.M).group(1)

    dns_utils.set_single_a_record(str(path), "demo", "10.10.10.10")
    updated = _read(path)
    assert "demo  IN A 10.10.10.10" in updated

    bumped_serial = re.search(dns_utils.SERIAL_LINE, updated, flags=re.M).group(1)
    assert int(bumped_serial) == int(original_serial) + 1


def test_set_single_a_record_appends_when_missing_label():
    path = Path(
        dns_utils.write_zone_file("demo", "172.60.0.53", "demo.sim.local", 60, 60)
    )
    dns_utils.set_single_a_record(str(path), "newlabel", "192.168.1.1")
    assert "newlabel  IN A 192.168.1.1" in _read(path)


def test_set_multi_a_records_replaces_block():
    path = Path(
        dns_utils.write_zone_file("demo", "172.60.0.53", "demo.sim.local", 60, 60)
    )
    dns_utils.set_multi_a_records(
        str(path), "demo", ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    )
    content = _read(path)
    lines = [line for line in content.splitlines() if line.startswith("demo")]
    assert lines == [
        "demo  IN A 10.0.0.1",
        "demo  IN A 10.0.0.2",
        "demo  IN A 10.0.0.3",
    ]


def test_write_flux_agents_replaces_directory_with_file(monkeypatch, tmp_path):
    target_dir = tmp_path / "dns_config"
    target_dir.mkdir()
    mistaken_dir = target_dir / "flux_agents_demo.txt"
    mistaken_dir.mkdir()

    path = Path(dns_utils.write_flux_agents("demo", ["1.1.1.1", "2.2.2.2"]))
    assert path.exists()
    assert path.read_text().strip().splitlines() == ["1.1.1.1", "2.2.2.2"]

    backups = list(target_dir.glob("flux_agents_demo.txt.backup_*"))
    assert backups, "Original directory should have been moved aside"


def test_set_zone_ttl_updates_directive_and_bumps_serial():
    path = Path(
        dns_utils.write_zone_file("demo", "172.60.0.53", "demo.sim.local", 60, 60)
    )
    before = _read(path)
    before_serial = int(re.search(dns_utils.SERIAL_LINE, before, flags=re.M).group(1))

    dns_utils.set_zone_ttl(str(path), 180)

    after = _read(path)
    assert after.splitlines()[0] == "$TTL 180"
    after_serial = int(re.search(dns_utils.SERIAL_LINE, after, flags=re.M).group(1))
    assert after_serial == before_serial + 1
