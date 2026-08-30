# global-ai-captions

A Flask webhook that receives property submissions from Tally, writes three
luxury real-estate captions with OpenAI, and sends them to the client through
Resend.

## Setup

Add these values in Replit Secrets:

- `OPENAI_API_KEY` — required for caption generation. The app also accepts
  `OPEN_API_KEY` for compatibility with the secret already added.
- `RESEND_API_KEY` — required for email delivery. The Resend connection may
  provide this automatically.

Optional environment variables:

- `OPENAI_MODEL` — defaults to `gpt-4o-mini`.
- `RESEND_FROM_EMAIL` — defaults to `Global AI Captions <onboarding@resend.dev>`.
  Use a verified Resend sender for production.
- `TALLY_WEBHOOK_SECRET` — enables HMAC verification for
  `X-Tally-Signature` or `Tally-Signature`.

## Tally configuration

Set the Tally webhook URL to:

```text
https://<your-app-domain>/webhook
```

The handler accepts Tally's normal `data.fields` payload and matches these
labels (case-insensitively):

- Property details
- Bedrooms
- Location
- Client email

It also accepts direct JSON keys with equivalent names for local testing.

## Local smoke test

With the app running, send a sample request:

```bash
curl -X POST http://localhost:8000/webhook \
  -H 'Content-Type: application/json' \
  -d '{
    "eventType": "FORM_RESPONSE",
    "data": {
      "submissionId": "sample-submission",
      "fields": [
        {"label": "Property details", "value": "Sun-filled modern residence with limestone terraces and a private garden."},
        {"label": "Bedrooms", "value": "4"},
        {"label": "Location", "value": "Ikoyi, Lagos"},
        {"label": "Client email", "value": "client@example.com"}
      ]
    }
  }'
```

The endpoint returns the three captions and the Resend message ID after
delivery. Missing configuration returns a clear `503` instead of fabricating
output.