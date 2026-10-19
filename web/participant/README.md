# Participant web app

The participant app is a static browser client in `web/`. It presents
programme-provided themes and content, approved and candidate entities, and
participant account and award views. It does not own domain data or decide
programme eligibility.

## Development

The local Compose stack does not start this client. The Helm chart can deploy
its image when `web.enabled` is set; that option is disabled by default. The
image contains static files and listens on container port `8080`.

From this directory, run the client checks with:

```bash
npm ci
npm test
python3 -m unittest discover -s tests -v
```

The [participant workflow](../../.github/workflows/participant.yml) runs these
checks and builds the image. For local API and Admin development, use the
[Compose instructions](../../deploy/README.md); the Gateway is exposed on port
`8080` and Admin on port `8090`.

## Further documentation

- [Project charter](https://github.com/myota-platform/myota-docs/blob/main/docs/project-charter.md)
- [Repository and service boundaries](https://github.com/myota-platform/myota-docs/blob/main/docs/architecture/repository-map.md)
- [Participant product gaps](https://github.com/myota-platform/myota-docs/blob/main/docs/governance/charter-gap-analysis.md)
