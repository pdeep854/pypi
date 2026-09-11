#!/usr/bin/env python3
"""Decide which LLVM refs need wheels, and build the GitHub Actions matrix
for the ones that don't already have them."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path

import tomllib

sys.path.insert(0, str(Path(__file__).parents[1] / "packages" / "halide-llvm"))
from _version_provider import get_commit_info, version_from_tag

LLVM_REPO = "llvm/llvm-project"

# Besides main (always tracked), keep the two most recent release majors up
# to date: the current stable series (still getting point releases) and the
# next one (still in RC). Anything older than that is no longer refreshed.
TRACKED_PRIOR_MAJORS = (1, 2)

PLATFORMS = (
    {
        "platform": "x86-64-linux",
        "runner": "ubuntu-latest",
        "container": "quay.io/pypa/manylinux_2_28_x86_64",
        "toolchain": "x86-64-linux.cmake",
        "manylinux_plat": "manylinux_2_28_x86_64",
    },
    {
        "platform": "x86-32-linux",
        "runner": "ubuntu-latest",
        "toolchain": "x86-32-linux.cmake",
        "docker_image": "quay.io/pypa/manylinux_2_28_i686",
        "manylinux_plat": "manylinux_2_28_i686",
        "pin_gcc12": True,
    },
    {
        "platform": "arm-64-linux",
        "runner": "ubuntu-24.04-arm",
        "container": "quay.io/pypa/manylinux_2_28_aarch64",
        "toolchain": "arm-64-linux.cmake",
        "manylinux_plat": "manylinux_2_28_aarch64",
    },
    {
        "platform": "arm-32-linux",
        "runner": "ubuntu-24.04-arm",
        "toolchain": "arm-32-linux.cmake",
        "docker_image": "quay.io/pypa/manylinux_2_31_armv7l",
        "manylinux_plat": "manylinux_2_31_armv7l",
    },
    {
        "platform": "x86-64-macos",
        "runner": "macos-15-intel",
        "toolchain": "x86-64-macos.cmake",
    },
    {
        "platform": "arm-64-macos",
        "runner": "macos-15",
        "toolchain": "arm-64-macos.cmake",
    },
    {
        "platform": "x86-64-windows",
        "runner": "windows-2022",
        "toolchain": "x86-64-windows.cmake",
        "msvc_arch": "amd64",
    },
    {
        "platform": "arm-64-windows",
        "runner": "windows-11-arm",
        "toolchain": "arm64-windows.cmake",
        "msvc_arch": "arm64",
        "wheel_plat": "win_arm64",
    },
    {
        "platform": "x86-32-windows",
        "runner": "windows-2022",
        "toolchain": "x86-32-windows.cmake",
        "msvc_arch": "amd64_x86",
        "wheel_plat": "win32",
    },
)


def resolved_ref_and_pattern(
    ref: str,
    tag_version: Callable[[str], str | None] = version_from_tag,
    commit_info: Callable[[str], tuple[str, int]] = get_commit_info,
) -> tuple[str, str]:
    if version := tag_version(ref):
        return ref, f"halide_llvm-{version}-"
    sha, _ = commit_info(ref)
    return sha, f"g{sha[:8]}"


def should_build(
    ref: str, asset_names: Iterable[str], **providers: object
) -> tuple[bool, str]:
    resolved_ref, pattern = resolved_ref_and_pattern(ref, **providers)
    return not any(pattern in name for name in asset_names), resolved_ref


def package_name() -> str:
    with (
        Path(__file__).parents[1] / "packages" / "halide-llvm" / "pyproject.toml"
    ).open("rb") as file:
        return tomllib.load(file)["project"]["name"]


def github_release_asset_names(project: str) -> list[str]:
    names: list[str] = []
    page = 1
    while True:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/releases?per_page=100&page={page}",
            headers={
                "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            releases = json.load(response)
        if not releases:
            return names
        for release in releases:
            if release["tag_name"].startswith(f"{project}@"):
                names.extend(asset["name"] for asset in release.get("assets", []))
        page += 1


def github_api(url: str) -> object:
    """GET a GitHub API URL, authenticated if a token is available."""
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main_branch_major(fetch: Callable[[str], object] = github_api) -> int:
    """Read LLVM_VERSION_MAJOR directly off llvm/llvm-project@main.

    Reads the version file via the Contents API instead of cloning the repo,
    since all we need is a single integer.
    """
    candidates = ("cmake/Modules/LLVMVersion.cmake", "llvm/CMakeLists.txt")
    for path in candidates:
        try:
            contents = fetch(
                f"https://api.github.com/repos/{LLVM_REPO}/contents/{path}?ref=main"
            )
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        text = base64.b64decode(contents["content"]).decode()
        if match := re.search(r"set\(\s*LLVM_VERSION_MAJOR\s+\"?(\d+)\"?\s*\)", text):
            return int(match.group(1))
    raise RuntimeError(
        "Could not determine LLVM's current major version from main: "
        + ", ".join(candidates)
    )


def latest_tag_for_major(
    major: int, fetch: Callable[[str], object] = github_api
) -> str | None:
    """Return the newest release or RC tag for an LLVM major version.

    None if that major has no tags yet (e.g. its release branch hasn't been
    cut, or has been cut but not tagged yet).
    """
    refs = fetch(
        f"https://api.github.com/repos/{LLVM_REPO}/git/matching-refs/tags/llvmorg-{major}."
    )
    tag_pattern = re.compile(rf"^llvmorg-{major}\.(\d+)\.(\d+)(?:-rc(\d+))?$")

    def sort_key(tag: str) -> tuple[int, int, int, int]:
        minor, patch, rc = tag_pattern.match(tag).groups()
        # A final release outranks every RC of the same minor.patch.
        return int(minor), int(patch), 1 if rc is None else 0, int(rc or 0)

    tags = [
        ref["ref"].removeprefix("refs/tags/")
        for ref in refs
        if tag_pattern.match(ref["ref"].removeprefix("refs/tags/"))
    ]
    return max(tags, key=sort_key) if tags else None


def candidate_refs(
    explicit_ref: str | None,
    major_fetch: Callable[[], int] = main_branch_major,
    tag_fetch: Callable[[int], str | None] = latest_tag_for_major,
) -> list[str]:
    """Refs to consider this run.

    A caller-supplied ref (e.g. from workflow_dispatch) is used as-is and
    alone. Otherwise, discover main plus the latest tag for each tracked
    prior major version.
    """
    if explicit_ref:
        return [explicit_ref]
    current_major = major_fetch()
    refs = ["main"]
    for age in TRACKED_PRIOR_MAJORS:
        if tag := tag_fetch(current_major - age):
            refs.append(tag)
    return refs


def build_matrix(
    refs: Iterable[str], asset_names: Iterable[str], **providers: object
) -> list[dict[str, object]]:
    """Build the platform x ref matrix for every ref that needs wheels."""
    asset_names = list(asset_names)
    matrix: list[dict[str, object]] = []
    for ref in refs:
        build, resolved_ref = should_build(ref, asset_names, **providers)
        print(f"{resolved_ref}: should_build={str(build).lower()}")
        if build:
            matrix.extend({"ref": resolved_ref, **platform} for platform in PLATFORMS)
    return matrix


def main() -> None:
    explicit_ref = os.environ.get("HALIDE_LLVM_REF") or None
    refs = candidate_refs(explicit_ref)
    matrix = build_matrix(refs, github_release_asset_names(package_name()))
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"should_build={'true' if matrix else 'false'}\n")
        output.write(f"platform_count={len(PLATFORMS)}\n")
        output.write(
            f"matrix={json.dumps({'include': matrix}, separators=(',', ':'))}\n"
        )


if __name__ == "__main__":
    main()
