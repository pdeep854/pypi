#!/usr/bin/env python3
"""Publish wheel files as `<project>@<version>` GitHub releases."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from email import policy
from email.parser import BytesParser
from pathlib import Path

DEFAULT_DIST_DIR = Path("dist")


def distribution_directory(environment: Mapping[str, str]) -> Path:
    """Return the artifact directory, defaulting to the workflows' dist/ path."""
    return Path(environment.get("DIST_DIR", DEFAULT_DIST_DIR))


def distribution_identity(wheel: Path) -> tuple[str, str]:
    """Read the canonical project name and version from wheel metadata."""
    with zipfile.ZipFile(wheel) as archive:
        metadata_files = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise RuntimeError(
                f"{wheel}: expected exactly one .dist-info/METADATA file, "
                f"found {len(metadata_files)}"
            )
        metadata = BytesParser(policy=policy.default).parsebytes(
            archive.read(metadata_files[0])
        )

    name, version = metadata["Name"], metadata["Version"]
    if not name or not version or "@" in name or "@" in version:
        raise RuntimeError(f"{wheel}: invalid release identity {name!r}@{version!r}")
    return name, version


def wheels_by_release(wheels: Iterable[Path]) -> dict[str, list[Path]]:
    """Group wheels using their metadata rather than their normalized filenames."""
    grouped: dict[str, list[Path]] = defaultdict(list)
    for wheel in sorted(wheels):
        name, version = distribution_identity(wheel)
        grouped[f"{name}@{version}"].append(wheel)
    return dict(grouped)


def publish_releases(
    releases: dict[str, list[Path]],
    repository: str,
    workflow: str,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> None:
    """Create releases or replace their wheel assets with GitHub CLI."""
    for tag, files in releases.items():
        view = run(
            ["gh", "release", "view", tag, "--repo", repository],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if view.returncode == 0:
            command = [
                "gh",
                "release",
                "upload",
                tag,
                *map(str, files),
                "--repo",
                repository,
                "--clobber",
            ]
        else:
            command = [
                "gh",
                "release",
                "create",
                tag,
                *map(str, files),
                "--repo",
                repository,
                "--title",
                tag,
                "--notes",
                f"Automated build from {workflow}",
            ]
        run(command, check=True)


def main() -> None:
    dist_dir = distribution_directory(os.environ)
    wheels = list(dist_dir.glob("*.whl"))
    if not wheels:
        sys.exit(f"No wheels found in {dist_dir}")
    publish_releases(
        wheels_by_release(wheels),
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_WORKFLOW"],
    )


if __name__ == "__main__":
    main()
