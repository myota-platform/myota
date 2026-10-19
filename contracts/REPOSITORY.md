# Contract ownership and validation

`contracts/openapi.yaml` is the canonical HTTP contract. The event registry,
JSON Schemas, and client façades in this directory are the corresponding
sources for event compatibility and supported client operations. Service
handlers own authorization, transactions, idempotency, and runtime behavior.

## Change workflow

1. Update the contract and the owning service implementation together.
2. Update event schemas and clients when the public shape changes.
3. Preserve explicit lifecycle commands when they represent audited domain
   transitions; avoid aliases without a client need.
4. Keep `route-inventory.json` and generated files in sync using the repository
   scripts and checks.
5. Update cross-service architecture or policy in
   [myota-docs](https://github.com/myota-platform/myota-docs), not in this
   repository's component README files.

The contract does not own service data or database migrations. Geodata imports
are programme-independent; entity categories use the shared catalogue, and
programme assignment and eligibility remain separate decisions. Event payloads
must follow the privacy, compatibility, and size rules in [events.md](events.md).

## Checks

From the repository root:

```bash
python3 -m unittest discover -s contracts/tests -v
python3 contracts/scripts/check_generated_clients.py
```

The [Contracts workflow](../.github/workflows/contracts.yml) runs the full
workspace checks, including service route and event-source compatibility.
