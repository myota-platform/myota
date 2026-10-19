# MyOTA Administration Web

The authenticated Vue 3 application for platform and programme administration.
It uses the Identity, Geodata, Programmes, and Activity APIs; authorization is
enforced by those services, with the UI providing role-aware navigation and
controls. The participant application is maintained separately in
[`web/participant`](../participant/README.md).

## Local development

From this directory, install dependencies and start the Vite development
server:

```bash
npm install
npm run dev
```

Vite serves the app on port 8090 and proxies API requests to
`http://localhost:8080` by default. The deployment Compose stack exposes the
built app on `http://localhost:8090`. See [deployment and local stack
instructions](../../deploy/README.md) for the full service stack.

Useful package scripts:

```bash
npm run typecheck
npm test
npm run lint
npm run build
npm run test:e2e
```

## Guides

- [Administration workflows](docs/administration-workflows.md)
- [Programme configuration](docs/programme-configuration.md)
- [Entity catalogue editor guide](https://github.com/myota-platform/myota-docs/blob/main/docs/domain/administration/entity-catalogue-editor.md)
- [Award designer guide](https://github.com/myota-platform/myota-docs/blob/main/docs/domain/awards/admin-designer.md)
- [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/)

The application vendors pinned Leaflet, MarkerCluster, and Geoman assets under
`public/vendor` for consistent map behavior across development and production.
