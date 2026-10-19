# Programme service

Programme owns programme configuration, shared entity categories, themes, and
programme policy. It uses the Core PostgreSQL database and exposes its API on
port `8002`. Activity consumes programme-owned award rules through the service
boundary.

## Development

From this directory:

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 run_programmes.py
```

Durable operation requires `CORE_DATABASE_URL` and
`MYOTA_REQUIRE_DURABILITY=1`. Use the local Compose stack for dependent services
and deployment configuration.

## Further documentation

- [Programme configuration and policy](https://github.com/myota-platform/myota-docs/tree/main/docs/domain/programmes)
- [Repository and service boundaries](https://github.com/myota-platform/myota-docs/blob/main/docs/architecture/repository-map.md)
