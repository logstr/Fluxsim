import json
from pathlib import Path

import pytest

from fluxsim import state


@pytest.fixture(autouse=True)
def reset_state():
    state.reset()
    yield
    state.reset()


@pytest.fixture(autouse=True)
def temp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_write_registry_creates_snapshot(tmp_path):
    state.NETWORKS["fluxy"] = state.Net(
        name="fluxy",
        kind="flux",
        subnet_octet=60,
        subnet="172.60.0.0/24",
        size=3,
        ttl=30,
        flux_interval=10,
        flux_selector="roundrobin",
    )

    state.write_registry(state.NETWORKS)
    registry_path = Path(state.REGISTRY_PATH)
    assert registry_path.exists()

    payload = json.loads(registry_path.read_text())
    assert "updated_at" in payload
    snapshot = payload["networks"]["fluxy"]
    assert snapshot["fqdn"] == "fluxy.sim.local"
    assert snapshot["dns_ip"] == "172.60.0.53"
    assert snapshot["flux_interval"] == 10
    assert snapshot["size"] == 3


def test_write_registry_overwrites_previous_content(tmp_path):
    # create dummy file
    registry_path = Path(state.REGISTRY_PATH)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("{}")

    state.NETWORKS["cdn"] = state.Net(
        name="cdn",
        kind="cdn",
        subnet_octet=61,
        subnet="172.61.0.0/24",
    )

    state.write_registry(state.NETWORKS)
    payload = json.loads(registry_path.read_text())
    assert "cdn" in payload["networks"]
