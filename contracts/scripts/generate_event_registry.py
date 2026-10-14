#!/usr/bin/env python3
"""Generate per-event schema wrappers from the checked-in event registry."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "contracts/event-registry.json"
SCHEMA_DIR = ROOT / "contracts/schemas/events"
WORK_SCHEMA_DIR = ROOT / "contracts/schemas/work"


def event_schema(event: dict) -> dict:
    event_type = event["eventType"]
    safe = event_type.replace(".", "-")
    properties = {"eventType": {"const": event_type}}
    if "payloadSchema" in event:
        properties["payload"] = event["payloadSchema"]
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://github.com/myota-platform/myota-contracts/contracts/schemas/events/{safe}.schema.json",
        "title": f"{event_type} envelope v1",
        "allOf": [
            {"$ref": "../event-envelope.schema.json"},
            {
                "type": "object",
                "properties": properties,
            },
        ],
    }
    if "payloadSchema" in event:
        schema["x-payload-evidence"] = event["payloadEvidence"]
        schema["x-data-classification"] = event["dataClassification"]
    return schema


def work_schema(work: dict) -> dict:
    work_type = work["workType"]
    safe = work_type.replace(".", "-")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://github.com/myota-platform/myota-contracts/contracts/schemas/work/{safe}.schema.json",
        "title": f"{work_type} command envelope v1",
        "allOf": [
            {"$ref": "../work-command.schema.json"},
            {
                "type": "object",
                "properties": {
                    "workType": {"const": work_type},
                    "payload": work["payloadSchema"],
                },
            },
        ],
        "x-payload-evidence": work["payloadEvidence"],
        "x-work-id-source": work["workIdSource"],
        "x-producer-sources": work["producerSources"],
        "x-consumer-sources": work["consumerSources"],
    }


def main() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    events = registry["events"]
    work = registry["work"]
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    WORK_SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    expected_events = set()
    for event in events:
        path = ROOT / "contracts" / event["schema"]
        expected_events.add(path)
        path.write_text(
            json.dumps(event_schema(event), indent=2) + "\n",
            encoding="utf-8",
        )
    expected_work = set()
    for item in work:
        path = ROOT / "contracts" / item["schema"]
        expected_work.add(path)
        path.write_text(
            json.dumps(work_schema(item), indent=2) + "\n",
            encoding="utf-8",
        )
    for stale in SCHEMA_DIR.glob("*.schema.json"):
        if stale not in expected_events:
            stale.unlink()
    for stale in WORK_SCHEMA_DIR.glob("*.schema.json"):
        if stale not in expected_work:
            stale.unlink()
    print(
        f"generated {len(events)} fact and {len(work)} work schemas from {REGISTRY}"
    )


if __name__ == "__main__":
    main()
