#!/usr/bin/env python3
"""Synchronize the checked-in OpenAPI mirrors from the canonical document."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from generate_deploy_event_registry import runtime_catalog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-root", type=Path, required=True)
    parser.add_argument("--deploy-root", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    canonical = root / "contracts" / "openapi.yaml"
    for mirror in (
        root / "openapi.yaml",
        args.platform_root / "contracts" / "openapi.yaml",
    ):
        mirror.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(canonical, mirror)
        print(f"synced {mirror}")
    source_contracts = root / "contracts"
    mirror_contracts = args.platform_root / "contracts"
    for relative in (
        Path("events.md"),
        Path("event-registry.json"),
        Path("schemas"),
    ):
        source = source_contracts / relative
        mirror = mirror_contracts / relative
        if source.is_dir():
            if mirror.exists():
                shutil.rmtree(mirror)
            shutil.copytree(source, mirror)
        else:
            mirror.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, mirror)
        print(f"synced {mirror}")
    catalog = runtime_catalog(
        json.loads(
            (source_contracts / "event-registry.json").read_text(
                encoding="utf-8"
            )
        )
    )
    catalog_content = json.dumps(catalog, indent=2) + "\n"
    destinations = [args.platform_root / "services" / "event_registry.json"]
    if args.deploy_root:
        destinations.append(
            args.deploy_root / "services" / "event_registry.json"
        )
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(catalog_content, encoding="utf-8")
        print(f"generated {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
