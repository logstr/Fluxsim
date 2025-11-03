import importlib


def test_fluxsim_importable() -> None:
    module = importlib.import_module("fluxsim")
    cli_module = importlib.import_module("fluxsim.cli")
    assert module.__name__ == "fluxsim"
    assert cli_module.__name__ == "fluxsim.cli"
