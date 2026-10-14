#!/usr/bin/env python3
"""Check the frozen HTTP contract against service route registries.

This intentionally uses only the Python standard library.  The repositories
currently expose small Python route dictionaries, while the canonical OpenAPI
file is YAML.  Phase 0 needs a deterministic drift check without requiring a
runtime framework or a database, so this script extracts the stable path and
method declarations from both representations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD")
REGISTRY_ROUTE = re.compile(
    r"\(\s*['\"]("
    + "|".join(METHODS)
    + r")['\"]\s*,\s*['\"](/v1/[^'\"]+)['\"]\s*,?\s*\)"
)
PATH_LINE = re.compile(r"^  (/v1/[^:]+):\s*$")
OPERATION_LINE = re.compile(
    r"^    (get|post|put|patch|delete|options|head):\s*$"
)
OPERATION_ID_LINE = re.compile(r"^\s+operationId:\s*([^\s#]+)")
ACTION_SEGMENTS = {
    "archive",
    "assign",
    "close",
    "content",
    "deactivate",
    "delete",
    "draw",
    "evaluate",
    "issue",
    "publish",
    "recalculate",
    "refresh",
    "render",
    "resolve",
    "review",
    "retire",
    "run",
    "submit",
    "unassign",
    "update",
    "upload",
    "verify",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract_routes(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    routes: list[dict[str, str]] = []
    operation_ids: list[str] = []
    current_path: str | None = None
    current_method: str | None = None
    current_operation_id: str | None = None
    in_paths = False

    def flush() -> None:
        nonlocal current_method, current_operation_id
        if current_path and current_method:
            item = {"method": current_method, "path": current_path}
            if current_operation_id:
                item["operationId"] = current_operation_id
                operation_ids.append(current_operation_id)
            routes.append(item)
        current_method = None
        current_operation_id = None

    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "paths:":
            in_paths = True
            continue
        if in_paths and line and not line.startswith(" "):
            flush()
            in_paths = False
            current_path = None
            continue
        if not in_paths:
            continue
        path_match = PATH_LINE.match(line)
        if path_match:
            flush()
            current_path = path_match.group(1)
            continue
        operation_match = OPERATION_LINE.match(line)
        if operation_match:
            flush()
            current_method = operation_match.group(1).upper()
            continue
        operation_id_match = OPERATION_ID_LINE.match(line)
        if operation_id_match and current_method:
            current_operation_id = operation_id_match.group(1)
    flush()
    return sorted(
        routes, key=lambda item: (item["path"], item["method"])
    ), operation_ids


def service_routes(root: Path) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    for source in sorted(root.rglob("*.py")):
        if any(part in {".", "__pycache__"} for part in source.parts):
            continue
        content = source.read_text(encoding="utf-8", errors="replace")
        for match in REGISTRY_ROUTE.finditer(content):
            routes.append(
                {
                    "service": source.stem,
                    "file": str(source.relative_to(root)),
                    "method": match.group(1),
                    "path": match.group(2),
                }
            )
    return sorted(
        routes, key=lambda item: (item["method"], item["path"], item["file"])
    )


def semantic_key(method: str, path: str) -> str | None:
    segments = path.rstrip("/").split("/")
    if not segments or segments[-1] not in ACTION_SEGMENTS:
        return None
    return f"{method} " + "/".join(segments[:-1] + ["{action}"])


def semantic_duplicates(routes: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for route in routes:
        key = semantic_key(route["method"], route["path"])
        if key:
            groups.setdefault(key, []).append(route)
    return [
        {"signature": key, "routes": value}
        for key, value in sorted(groups.items())
        if len({item["path"] for item in value}) > 1
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--mirror", action="append", type=Path, default=[])
    parser.add_argument(
        "--service-root", action="append", type=Path, default=[]
    )
    parser.add_argument("--semantic-baseline", type=Path)
    parser.add_argument("--inventory-out", type=Path)
    args = parser.parse_args()

    errors: list[str] = []
    for mirror in args.mirror:
        if not mirror.exists():
            errors.append(f"missing contract mirror: {mirror}")
        elif sha256(args.canonical) != sha256(mirror):
            errors.append(f"contract mirror differs from canonical: {mirror}")

    contract, operation_ids = contract_routes(args.canonical)
    contract_set = {(item["method"], item["path"]) for item in contract}
    duplicate_operation_ids = sorted(
        {item for item in operation_ids if operation_ids.count(item) > 1}
    )
    if duplicate_operation_ids:
        errors.append(
            "duplicate OpenAPI operationIds: "
            + ", ".join(duplicate_operation_ids)
        )

    registries = [
        route for root in args.service_root for route in service_routes(root)
    ]
    registry_set = {(item["method"], item["path"]) for item in registries}
    missing_contract = sorted(registry_set - contract_set)
    missing_registry = sorted(contract_set - registry_set)
    if missing_contract:
        errors.append(
            "routes registered by a service but absent from the canonical contract: "
            + ", ".join(
                f"{method} {path}" for method, path in missing_contract
            )
        )
    if missing_registry:
        errors.append(
            "contract operations without a scanned service registration: "
            + ", ".join(
                f"{method} {path}" for method, path in missing_registry
            )
        )

    semantic_candidates = semantic_duplicates(contract)
    if args.semantic_baseline:
        baseline = json.loads(
            args.semantic_baseline.read_text(encoding="utf-8")
        )
        expected = {
            item["signature"]: sorted(item["paths"])
            for item in baseline.get("candidates", [])
        }
        actual = {
            item["signature"]: sorted(
                route["path"] for route in item["routes"]
            )
            for item in semantic_candidates
        }
        if expected != actual:
            errors.append(
                "semantic duplicate candidates differ from the reviewed baseline"
            )

    inventory = {
        "canonical": str(args.canonical),
        "canonicalSha256": sha256(args.canonical),
        "contractOperations": contract,
        "serviceRoutes": registries,
        "missingContractRoutes": [
            {"method": method, "path": path}
            for method, path in missing_contract
        ],
        "missingServiceRegistrations": [
            {"method": method, "path": path}
            for method, path in missing_registry
        ],
        "duplicateOperationIds": duplicate_operation_ids,
        "semanticDuplicateCandidates": semantic_candidates,
    }
    if args.inventory_out:
        args.inventory_out.parent.mkdir(parents=True, exist_ok=True)
        args.inventory_out.write_text(
            json.dumps(inventory, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "canonicalSha256": inventory["canonicalSha256"],
                "contractOperations": len(contract),
                "serviceRoutes": len(registries),
                "missingContractRoutes": len(missing_contract),
                "missingServiceRegistrations": len(missing_registry),
                "duplicateOperationIds": len(duplicate_operation_ids),
                "semanticDuplicateCandidates": len(
                    inventory["semanticDuplicateCandidates"]
                ),
            },
            indent=2,
        )
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
