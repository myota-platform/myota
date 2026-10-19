# Identity service

Identity owns accounts, authentication, callsigns, roles, sessions, recovery,
and security events. It uses the Core PostgreSQL database and exposes the
Identity API on port `8001`.

## Development

From this directory:

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 run_identity.py
```

Durable operation requires `CORE_DATABASE_URL` and
`MYOTA_REQUIRE_DURABILITY=1`. Use the local Compose stack for dependent services
and deployment configuration.

## Further documentation

- [Identity policy and security](https://github.com/myota-platform/myota-docs/tree/main/docs/domain/identity)
- [Current system state](https://github.com/myota-platform/myota-docs/blob/main/docs/architecture/current-state.md)
- [Database migration ownership](../../deploy/db/README.md)
