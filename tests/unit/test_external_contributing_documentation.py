#!/usr/bin/env python3
# Copyright (C) 2025 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[2]
REQUIREMENTS_TXT = PROJECT_ROOT / "requirements.txt"
PACKAGES_DIRECTORY = PROJECT_ROOT / "packages"
BOOTSTRAP_SCRIPT = PROJECT_ROOT / "scripts/external/bootstrap-python-env"


def test_project_root_is_valid() -> None:
    assert (PROJECT_ROOT / ".git").exists(), "Perhaps you moved this test module!"


def test_requirements_txt_exists_in_project_root() -> None:
    assert REQUIREMENTS_TXT.exists()


@pytest.mark.parametrize("dependency", ["mypy", "ruff"])
def test_required_dev_dependencies_are_installed(dependency: str) -> None:
    try:
        importlib.import_module(dependency)
    except ImportError:
        pytest.fail(
            f"{dependency!r} dependency not found in environment.\n"
            "Did you activate the virtual environment?"
        )


def test_all_python_packages_are_included_in_bootstrap_script() -> None:
    bootstrap_content = (BOOTSTRAP_SCRIPT).read_text()
    package_directories = [p for p in (PACKAGES_DIRECTORY).iterdir() if p.is_dir()]
    python_packages = [p for p in package_directories if (p / "pyproject.toml").exists()]
    assert all(p.name in bootstrap_content for p in python_packages)
