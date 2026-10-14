#!/usr/bin/env python3
"""Fail when source-owned runtime/artifact mirrors drift."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def tree_files(directory: Path) -> dict[str, Path]:
    return {
        path.relative_to(directory).as_posix(): path
        for path in directory.rglob("*")
        if path.is_file()
    }


def main() -> int:
    root = (
        Path(sys.argv[1]).resolve()
        if len(sys.argv) > 1
        else Path("..").resolve()
    )
    manifest = (
        Path(__file__).resolve().parents[1]
        / "contracts"
        / "runtime-mirror-map.json"
    )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    errors: list[str] = []
    mirror_count = 0

    for entry in data["entries"]:
        source = root / entry["owner"] / entry["path"]
        if not source.is_file():
            errors.append(
                f"missing owner source: {entry['owner']}/{entry['path']}"
            )
            continue
        for mirror in entry["mirrors"]:
            mirror_count += 1
            target = root / mirror
            if not target.is_file():
                errors.append(
                    f"missing mirror: {mirror} "
                    f"(from {entry['owner']}/{entry['path']})"
                )
            elif target.read_bytes() != source.read_bytes():
                errors.append(
                    f"drift: {mirror} differs from "
                    f"{entry['owner']}/{entry['path']}"
                )

    for entry in data.get("retiredEntries", []):
        source = root / entry["owner"] / entry["path"]
        if not entry.get("sourceRetired") and not source.is_file():
            errors.append(
                f"missing retired source record: "
                f"{entry['owner']}/{entry['path']}"
            )
        for mirror in entry.get("formerMirrors", []):
            if (root / mirror).exists():
                errors.append(
                    f"retired mirror still exists: {mirror} "
                    f"(from {entry['owner']}/{entry['path']})"
                )

    tree_count = 0
    for entry in data.get("treeEntries", []):
        source = root / entry["owner"] / entry["path"]
        if not source.is_dir():
            errors.append(
                f"missing owner tree: {entry['owner']}/{entry['path']}"
            )
            continue
        source_files = tree_files(source)
        for mirror in entry["mirrors"]:
            tree_count += 1
            target = root / mirror
            if not target.is_dir():
                errors.append(
                    f"missing mirror tree: {mirror} "
                    f"(from {entry['owner']}/{entry['path']})"
                )
                continue
            target_files = tree_files(target)
            missing = sorted(source_files.keys() - target_files.keys())
            extra = sorted(target_files.keys() - source_files.keys())
            if missing:
                errors.append(
                    f"missing files in {mirror}: {', '.join(missing)}"
                )
            if extra:
                errors.append(f"extra files in {mirror}: {', '.join(extra)}")
            for relative in sorted(source_files.keys() & target_files.keys()):
                if (
                    source_files[relative].read_bytes()
                    != target_files[relative].read_bytes()
                ):
                    errors.append(f"drift: {mirror}/{relative}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(
        f"source mirror audit passed: {len(data['entries'])} owner files, "
        f"{mirror_count} file mirrors, {tree_count} exact tree mirrors, "
        f"{len(data.get('retiredEntries', []))} retired artifacts absent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
