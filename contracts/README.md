# Contracts

This directory owns the canonical OpenAPI document, event registry and
schemas, compatibility checks, and generated client façades.

- Start with [contract ownership and validation](REPOSITORY.md).
- See [event envelope and compatibility rules](events.md).
- Edit `openapi.yaml`, `event-registry.json`, and schemas here; do not edit
generated or deployment copies directly.

Run contract checks from the repository root with the
[Contracts workflow](../.github/workflows/contracts.yml).
