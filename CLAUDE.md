# Dispatch — Project Instructions

This project follows the global `AGENTS.md` and `SECURITY_BASELINE.md`.
The notes below cover only what's specific to this repository.

## Version identifiers

Three places, in sync at `v1.0.6`:

- `package.json` — the `version` field
- `public/index.html` — the `<title>`
- `api/index.py` — the `APP_VERSION` constant

`README.md`'s top-level heading still reads "Dispatch v1.0.2" — stale
documentation, flagged during governance migration, not corrected.

## Local development

`server.js` has **no `/api` proxy** — it only serves static files from
`public/` and a catch-all to `index.html`. The frontend calls `/api/*`
as relative paths, which only resolve through Vercel's rewrite rules.

Use `vercel dev` for local development that includes working API
calls. Running `node server.js` alone serves the UI but every `/api/*`
call will fail — this differs from most other apps in this ecosystem,
which proxy `/api/*` to a separately-run Flask process.
