#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BASE_VERSION_RE = re.compile(r"^\s*(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)(?:[-+].*)?\s*$")
SORTABLE_BASE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$")
PYPROJECT_VERSION_RE = re.compile(r'^\s*version\s*=\s*"([^"]+)"\s*$', re.MULTILINE)


@dataclass
class ReleaseTag:
    base_version: str
    release_iteration: int
    release_tag: str
    reused_tag_at_head: bool


def run_git_tag(*args: str) -> list[str]:
    output = subprocess.check_output(["git", "tag", *args], text=True)
    return [line.strip() for line in output.splitlines() if line.strip()]


def parse_base_version(raw_version: str) -> str:
    match = BASE_VERSION_RE.match(raw_version)
    if not match:
        raise ValueError(
            f'Unsupported version "{raw_version}". Expected e.g. "1.148.0" or "1.148.0rc1".'
        )
    base_version = match.group(1)
    parse_version_for_sort(base_version)
    return base_version


def parse_version_for_sort(version: str) -> tuple[int, int, int, int, int]:
    match = SORTABLE_BASE_VERSION_RE.fullmatch(version)
    if not match:
        raise ValueError(
            f'Unsupported base version "{version}". Expected e.g. "1.148.0" or "1.148.0rc1".'
        )

    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    prerelease_label = match.group(4)
    prerelease_number = int(match.group(5)) if match.group(5) else 0
    prerelease_rank = {None: 3, "rc": 2, "b": 1, "a": 0}[prerelease_label]
    return major, minor, patch, prerelease_rank, prerelease_number


def compatible_prefixes(prefix: str) -> list[str]:
    variants = [prefix]
    if len(prefix) == 1 and prefix.isalpha():
        swapped = prefix.swapcase()
        if swapped != prefix:
            variants.append(swapped)
    return variants


def build_prefix_pattern(prefix: str) -> str:
    options = "|".join(re.escape(value) for value in compatible_prefixes(prefix))
    return f"(?:{options})"


def get_base_version_from_tags(all_tags: list[str], base_prefix: str) -> str | None:
    prefix_pattern = build_prefix_pattern(base_prefix)
    base_re = re.compile(rf"^{prefix_pattern}(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)$")
    versions = [match.group(1) for tag in all_tags if (match := base_re.fullmatch(tag))]
    if not versions:
        return None
    return sorted(versions, key=parse_version_for_sort)[-1]


def get_release_iteration(
    tag: str, base_version: str, release_prefix: str, release_suffix: str
) -> int | None:
    prefix_pattern = build_prefix_pattern(release_prefix)
    suffix_pattern = re.escape(release_suffix)
    release_re = re.compile(
        rf"^{prefix_pattern}{re.escape(base_version)}-{suffix_pattern}\.(\d+)$"
    )
    match = release_re.fullmatch(tag)
    return int(match.group(1)) if match else None


def compute_release_tag(
    base_version: str,
    all_tags: list[str],
    head_tags: list[str],
    release_prefix: str,
    release_suffix: str,
) -> ReleaseTag:
    all_iterations = [
        value
        for value in (
            get_release_iteration(tag, base_version, release_prefix, release_suffix)
            for tag in all_tags
        )
        if value is not None
    ]
    max_iteration = max(all_iterations) if all_iterations else 0

    head_iterations = [
        (tag, value)
        for tag in head_tags
        for value in [
            get_release_iteration(tag, base_version, release_prefix, release_suffix)
        ]
        if value is not None
    ]
    if head_iterations:
        reused_tag, reused_iteration = sorted(
            head_iterations, key=lambda item: item[1], reverse=True
        )[0]
        return ReleaseTag(
            base_version=base_version,
            release_iteration=reused_iteration,
            release_tag=reused_tag,
            reused_tag_at_head=True,
        )

    next_iteration = max_iteration + 1
    return ReleaseTag(
        base_version=base_version,
        release_iteration=next_iteration,
        release_tag=f"{release_prefix}{base_version}-{release_suffix}.{next_iteration}",
        reused_tag_at_head=False,
    )


def write_github_output(result: ReleaseTag) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return

    with open(output_path, "a", encoding="utf-8") as output_file:
        output_file.write(f"base_version={result.base_version}\n")
        output_file.write(f"release_iteration={result.release_iteration}\n")
        output_file.write(f"release_tag={result.release_tag}\n")
        output_file.write(
            f"reused_tag_at_head={str(result.reused_tag_at_head).lower()}\n"
        )


def read_pyproject_version() -> str | None:
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    contents = pyproject_path.read_text(encoding="utf-8")
    match = PYPROJECT_VERSION_RE.search(contents)
    if not match:
        return None
    return match.group(1).strip()


def main() -> int:
    release_prefix = (os.getenv("RELEASE_TAG_PREFIX") or "v").strip()
    base_prefix = (os.getenv("BASE_TAG_PREFIX") or release_prefix).strip()
    release_suffix = (os.getenv("RELEASE_TAG_SUFFIX") or "mindroom").strip()

    if not release_prefix:
        raise ValueError("RELEASE_TAG_PREFIX must not be empty")
    if not release_suffix:
        raise ValueError("RELEASE_TAG_SUFFIX must not be empty")

    all_tags = run_git_tag("--list")
    head_tags = run_git_tag("--points-at", "HEAD")

    raw_version = os.getenv("BASE_VERSION")
    if raw_version:
        base_version = parse_base_version(raw_version)
    else:
        pyproject_version = read_pyproject_version()
        if pyproject_version:
            base_version = parse_base_version(pyproject_version)
        else:
            auto_base_version = get_base_version_from_tags(all_tags, base_prefix)
            if not auto_base_version:
                raise ValueError(
                    "Could not auto-detect base version. Set BASE_VERSION or provide pyproject.toml version."
                )
            base_version = auto_base_version

    result = compute_release_tag(
        base_version,
        all_tags,
        head_tags,
        release_prefix,
        release_suffix,
    )
    write_github_output(result)

    print(f"base_version={result.base_version}")
    print(f"release_iteration={result.release_iteration}")
    print(f"release_tag={result.release_tag}")
    print(f"reused_tag_at_head={str(result.reused_tag_at_head).lower()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
