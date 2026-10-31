"""Dependency bootstrap tests never contact pip or the network."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import scraper_deps


@pytest.fixture
def deps(tmp_path, monkeypatch):
    # Match Stash's layout under an arbitrary user-selected source path.
    package = tmp_path / "custom-source-name" / "scraper_deps"
    package.mkdir(parents=True)
    source = Path(scraper_deps.__file__)
    shutil.copyfile(source, package / "__init__.py")
    spec = importlib.util.spec_from_file_location("test_deps", package / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    return module, package.parent / "automatic_dependencies"


def test_importable_module_skips_pip(deps, monkeypatch):
    module, directory = deps
    runner = Mock()
    monkeypatch.setattr(module.subprocess, "run", runner)
    module.ensure_requirements("json>=1")
    runner.assert_not_called()
    assert str(directory) in sys.path


@pytest.mark.parametrize(
    "spec, name, requirement",
    [
        ("missing_package>=5,<7", "missing_package", "missing_package>=5,<7"),
        (
            "different_import:distribution-name>=2",
            "different_import",
            "distribution-name>=2",
        ),
    ],
)
def test_missing_module_installs_and_imports(
    deps, monkeypatch, capsys, spec, name, requirement
):
    module, directory = deps
    importer = Mock(side_effect=[ModuleNotFoundError(name=name), object()])
    runner = Mock()
    monkeypatch.setattr(module.importlib, "import_module", importer)
    monkeypatch.setattr(module.subprocess, "run", runner)
    module.ensure_requirements(spec)
    runner.assert_called_once_with(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            str(directory),
            requirement,
        ],
        check=True,
        stdout=sys.stderr,
        stderr=sys.stderr,
    )
    assert importer.call_count == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "[Warning] First run" in output.err


@pytest.mark.parametrize(
    "error", [OSError("no pip"), subprocess.CalledProcessError(1, "pip")]
)
def test_pip_failure_names_package_and_command(deps, monkeypatch, error):
    module, directory = deps
    monkeypatch.setattr(
        module.importlib,
        "import_module",
        Mock(side_effect=ModuleNotFoundError(name="missing")),
    )
    monkeypatch.setattr(module.subprocess, "run", Mock(side_effect=error))
    with pytest.raises(SystemExit) as caught:
        module.ensure_requirements("missing>=1")
    message = str(caught.value)
    assert "[Error]" in message
    assert "missing>=1" in message
    assert "-m pip install --target" in message
    assert str(directory) in message


def test_existing_shared_dependency_does_not_reinstall(deps, monkeypatch):
    module, directory = deps
    directory.mkdir()
    (directory / "shared_fake_dependency.py").write_text("value = 42\n")
    runner = Mock()
    monkeypatch.setattr(module.subprocess, "run", runner)
    try:
        module.ensure_requirements("shared_fake_dependency>=1")
        runner.assert_not_called()
    finally:
        sys.modules.pop("shared_fake_dependency", None)


def test_relative_import_in_installed_layout(tmp_path):
    source = tmp_path / "not-the-default-source-name"
    package = source / "scraper_deps"
    scraper = source / "ColtStudio"
    package.mkdir(parents=True)
    scraper.mkdir()
    shutil.copyfile(Path(scraper_deps.__file__), package / "__init__.py")
    script = scraper / "check.py"
    script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n"
        "from scraper_deps import ensure_requirements\n"
        "ensure_requirements('json')\nprint('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "ok\n"
