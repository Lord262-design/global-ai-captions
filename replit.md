# global-ai-captions

Receives Tally property submissions, generates three luxury captions with OpenAI, and emails them to the client via Resend.

## Run & Operate

- `gunicorn --bind 0.0.0.0:${PORT:-8000} main:app` — run the Flask webhook (port 8000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required secrets: `OPENAI_API_KEY` (or `OPEN_API_KEY`) and `RESEND_API_KEY`

## Stack

- Python 3.13 and Flask
- OpenAI Python SDK for caption generation
- Resend API for transactional email delivery

## Where things live

- `main.py` — Flask application, Tally payload parsing, caption generation, and email delivery
- `README.md` — setup, Tally field expectations, and smoke-test instructions
- `sample_payload.json` — safe local webhook fixture

## Architecture decisions

- Tally signature verification is optional and activates when `TALLY_WEBHOOK_SECRET` is set.
- OpenAI output is required to be JSON with exactly three captions; malformed output fails explicitly.
- The webhook does not fabricate captions when either provider is misconfigured.

## Product

- A single `/webhook` endpoint accepts Tally form submissions.
- Three distinct luxury property captions are generated from property details, bedroom count, and location.
- Results are emailed automatically to the submitted client email through Resend.

## User preferences

No additional preferences recorded.

## Gotchas

- Set `RESEND_FROM_EMAIL` to a verified sender before production use.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
