# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""Build reproducible scraper packages and a Stash source index."""

import argparse
import hashlib
import re
import subprocess
import zipfile
from pathlib import Path
from typing import TypedDict

import yaml


class Package(TypedDict):
    id: str
    name: str
    directory: Path
    files: list[Path]
    requires: list[str]


def requirements(config: Path) -> list[str]:
    """Read dependency IDs from header comments, before the YAML body."""
    result = []
    for line in config.read_text().splitlines():
        if not line.strip():
            continue
        if not line.lstrip().startswith("#"):
            break
        match = re.match(r"\s*#\s*requires:\s*(.*)", line)
        if match:
            result.extend(match[1].split())
    return result


def script_paths(value):
    """Find Python script references in nested Stash action definitions."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "script" and isinstance(child, list):
                yield from (
                    arg for arg in child if isinstance(arg, str) and arg.endswith(".py")
                )
            else:
                yield from script_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from script_paths(child)


def python_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*.py")
        if not any(
            part in {"tests", "__pycache__"} or part.startswith(".")
            for part in path.relative_to(directory).parts
        )
    )


def discover_packages(root: Path) -> list[Package]:
    packages: list[Package] = []
    for config in sorted((root / "scrapers").glob("*/*.yml")):
        data = yaml.safe_load(config.read_text())
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("name"), str)
            or not data["name"].strip()
        ):
            raise ValueError(f"Missing name: {config}")
        library = config.name == "package.yml"
        package_id = config.parent.name if library else config.stem
        files = python_files(config.parent)
        if not library:
            files.append(config)
        for script in script_paths(data):
            path = (config.parent / script).resolve()
            if path not in [file.resolve() for file in files]:
                raise ValueError(f"Missing referenced script {script!r} in {config}")
        packages.append(
            {
                "id": package_id,
                "name": data["name"],
                "directory": config.parent,
                "files": sorted(files),
                "requires": requirements(config),
            }
        )
    ids = [package["id"] for package in packages]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate package IDs")
    for package in packages:
        for dependency in package["requires"]:
            if dependency not in ids:
                raise ValueError(
                    f"Unknown requires ID {dependency!r} in {package['id']}"
                )
    return packages


def last_commit(root: Path, directory: Path) -> tuple[str, str]:
    result = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--format=%h%n%ai",
            "--",
            str(directory.relative_to(root)),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = result.stdout.strip().splitlines()
    if len(lines) != 2:
        raise ValueError(f"No git history for {directory}")
    return lines[0], lines[1][:19]


def build_site(root: Path, out: Path) -> list[dict]:
    root = root.resolve()
    packages = discover_packages(root)
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for package in packages:
        version, date = last_commit(root, package["directory"])
        filename = f"{package['id']}.zip"
        archive = out / filename
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            for path in package["files"]:
                # Each archive extracts into Stash's own <source>/<id> folder.
                info = zipfile.ZipInfo(
                    path.relative_to(package["directory"]).as_posix(),
                    (1980, 1, 1, 0, 0, 0),
                )
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zipped.writestr(info, path.read_bytes())
        entry = {
            "id": package["id"],
            "name": package["name"],
            "version": version,
            "date": date,
            "path": filename,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        }
        if package["requires"]:
            entry["requires"] = package["requires"]
        entries.append(entry)
    (out / "index.yml").write_text(yaml.safe_dump(entries, sort_keys=False))
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, nargs="?", default=Path("_site"))
    args = parser.parse_args()
    try:
        entries = build_site(Path(__file__).resolve().parents[1], args.out)
    except (ValueError, OSError, subprocess.CalledProcessError, yaml.YAMLError) as exc:
        parser.exit(1, f"Build failed: {exc}\n")
    print(f"Built {len(entries)} packages into {args.out}")


if __name__ == "__main__":
    main()
