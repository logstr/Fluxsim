import importlib


def test_fluxsim_importable() -> None:
    module = importlib.import_module("fluxsim")
    assert hasattr(module, "cli"), "fluxsim package should expose cli module"
