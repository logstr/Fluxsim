import subprocess

from fluxsim import docker_utils


class DummyCompletedProcess:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def test_compose_returns_stdout(monkeypatch):
    captured_args = {}

    def fake_run(cmd, check, capture_output, text):
        captured_args["cmd"] = cmd
        return DummyCompletedProcess(stdout="ok\n")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = docker_utils.compose(["ps"], compose_file="compose.yml")

    assert result == "ok"
    assert captured_args["cmd"][:4] == [
        "docker",
        "compose",
        "-p",
        docker_utils.PROJECT_NAME,
    ]


def test_compose_returns_none_on_failure(monkeypatch, capsys):
    def fake_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "docker compose", stderr="boom")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = docker_utils.compose(["ps"], compose_file="compose.yml")
    assert result is None

    out = capsys.readouterr().out
    assert "[compose error]" in out


def test_service_container_ids_filters_blank_lines(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return DummyCompletedProcess(stdout="abc\n\n  \ndef\n")

    monkeypatch.setattr("subprocess.run", fake_run)
    ids = docker_utils.service_container_ids("dns", "compose.yml")
    assert ids == ["abc", "def"]


def test_container_ip_on_net_validates_ipv4(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return DummyCompletedProcess(stdout="10.0.0.5\n")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert docker_utils.container_ip_on_net("cid", "net") == "10.0.0.5"


def test_container_ip_on_net_returns_none_for_invalid(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return DummyCompletedProcess(stdout="not-an-ip\n")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert docker_utils.container_ip_on_net("cid", "net") is None
