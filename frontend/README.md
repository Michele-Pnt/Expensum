# Expensum web application

This directory contains the Next.js frontend for Expensum. For project
overview, prerequisites, and the complete local setup, see the repository
[README](../README.md) and [development guide](../docs/development.md).

## Run locally

```bash
npm ci
npm run dev
```

Open <http://localhost:3000>. Configure backend origins only with local
development values. Never put server credentials or private API keys in
`NEXT_PUBLIC_*` variables: Next.js embeds those values in browser bundles.

## Checks

```bash
npm test
npm run lint
npm run typecheck
```

Frontend changes are covered by the repository's MIT license; dependencies
retain their own licenses.
