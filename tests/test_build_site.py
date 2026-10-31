"""Offline tests for Stash's downloadable package format."""

import hashlib
import os
import subprocess
import zipfile

import pytest
import yaml

from scripts.build_site import build_site


@pytest.fixture
def tree(tmp_path):
    files = {
        "scrapers/example/Example.yml": (
            "# requires: scraper_deps\nname: Example\nsceneByURL:\n"
            "  - action: script\n    script: [python, example.py, scene]\n"
        ),
        "scrapers/example/example.py": "print('null')\n",
        "scrapers/example/tests/test_example.py": "excluded\n",
        "scrapers/example/__pycache__/cache.py": "excluded\n",
        "scrapers/example/.venv/lib/installed.py": "excluded\n",
        "scrapers/example/pyproject.toml": "excluded\n",
        "scrapers/example/uv.lock": "excluded\n",
        "scrapers/scraper_deps/package.yml": "name: Shared Python dependencies\n",
        "scrapers/scraper_deps/__init__.py": "# library\n",
        "scrapers/scraper_deps/helpers/nested.py": "# nested module\n",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "add", "scrapers"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Fixture",
        ],
        cwd=tmp_path,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": "2026-10-30T12:34:56+0000",
            "GIT_COMMITTER_DATE": "2026-10-30T12:34:56+0000",
        },
    )
    return tmp_path


def test_packages_index_and_reproducibility(tree):
    out = tree / "site"
    entries = build_site(tree, out)
    assert yaml.safe_load((out / "index.yml").read_text()) == entries
    assert [entry["id"] for entry in entries] == ["Example", "scraper_deps"]
    scraper, library = entries
    assert scraper["name"] == "Example"
    assert scraper["requires"] == ["scraper_deps"]
    assert "requires" not in library
    assert scraper["date"] == "2026-10-30 12:34:56"
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=tree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert scraper["version"] == f"{sha}-2026-10-30"
    for entry in entries:
        assert entry["path"] == f"{entry['id']}.zip"
        assert (
            entry["sha256"]
            == hashlib.sha256((out / entry["path"]).read_bytes()).hexdigest()
        )
    with zipfile.ZipFile(out / "Example.zip") as archive:
        assert archive.namelist() == ["Example.yml", "example.py"]
        assert all(
            item.date_time == (1980, 1, 1, 0, 0, 0) for item in archive.infolist()
        )
    with zipfile.ZipFile(out / "scraper_deps.zip") as archive:
        assert archive.namelist() == ["__init__.py", "helpers/nested.py"]
    before = {path.name: path.read_bytes() for path in out.iterdir()}
    os.utime(tree / "scrapers/example/example.py", (1800000000, 1800000000))
    build_site(tree, out)
    assert before == {path.name: path.read_bytes() for path in out.iterdir()}


@pytest.mark.parametrize(
    "content, message",
    [
        ("sceneByURL: []\n", "Missing name"),
        ("name: '  '\n", "Missing name"),
        ("# requires: nonexistent\nname: Example\n", "Unknown requires ID"),
        (
            "name: Example\nsceneByURL:\n  - script: [python, absent.py]\n",
            "Missing referenced script",
        ),
    ],
)
def test_invalid_package_fails(tree, content, message):
    (tree / "scrapers/example/Example.yml").write_text(content)
    with pytest.raises(ValueError, match=message):
        build_site(tree, tree / "site")


def test_new_package_needs_git_history(tree):
    path = tree / "scrapers/new"
    path.mkdir()
    (path / "New.yml").write_text("name: New\n")
    with pytest.raises(ValueError, match="No git history"):
        build_site(tree, tree / "site")
