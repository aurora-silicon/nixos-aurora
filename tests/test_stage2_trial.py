"""Run the Stage 2 trial suites from stage2/ with the repository tests.

stage2/test_bootchain.py is fedora-aurora's own suite for the shared updater,
stage2/test_nixos_stage2.py the NixOS transactions. Both need dtc; without it
they skip here, and checks.stage2-trial runs them in the package build.
"""
import importlib.util
from pathlib import Path

STAGE2 = Path(__file__).resolve().parents[1] / 'stage2'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, STAGE2 / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


suites = [load('stage2_bootchain_tests', 'test_bootchain.py'), load('stage2_nixos_tests', 'test_nixos_stage2.py')]


def load_tests(loader, tests, pattern):
    for module in suites:
        tests.addTests(loader.loadTestsFromModule(module))
    return tests
