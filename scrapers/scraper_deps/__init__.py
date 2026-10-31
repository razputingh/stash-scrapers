"""Install missing Python dependencies beside the source's scraper packages."""

import importlib
import re
import shlex
import subprocess
import sys
from pathlib import Path


def ensure_requirements(*specs: str) -> None:
    """Import each requirement, installing it only when its module is missing.

    Use ``import_name:distribution>=version`` when the names differ.
    Already importable modules are accepted without a version check.
    """
    deps_dir = Path(__file__).resolve().parent.parent / "automatic_dependencies"
    if str(deps_dir) not in sys.path:
        sys.path.insert(0, str(deps_dir))

    for spec in specs:
        import_name, separator, requirement = spec.partition(":")
        if not separator:
            requirement = spec
            match = re.match(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", requirement)
            if match is None:
                raise ValueError(f"Invalid requirement: {spec!r}")
            import_name = match.group().replace("-", "_")
        try:
            importlib.import_module(import_name)
            continue
        except ModuleNotFoundError as exc:
            # Do not hide a broken installed package's missing transitive import.
            if exc.name != import_name and not import_name.startswith(f"{exc.name}."):
                raise

        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            str(deps_dir),
            requirement,
        ]
        print(
            f"[Warning] First run: installing {requirement} into {deps_dir}.",
            file=sys.stderr,
        )
        try:
            # Keep pip output off the scraper's JSON-only stdout.
            subprocess.run(command, check=True, stdout=sys.stderr, stderr=sys.stderr)
            importlib.invalidate_caches()
            importlib.import_module(import_name)
        except (OSError, subprocess.CalledProcessError, ImportError) as exc:
            raise SystemExit(
                f"[Error] Cannot install/import {requirement}: {exc}. "
                "Stash's Python needs pip, network access, and a writable dependency "
                f"directory. Run: {shlex.join(command)}"
            ) from exc
