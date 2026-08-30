"""Global AI Captions — Tally webhook to luxury property email."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import requests
from flask import Flask, jsonify, request
from openai import OpenAI


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


class ConfigurationError(RuntimeError):
    """Raised when a required integration setting is unavailable."""


class PayloadError(ValueError):
    """Raised when Tally did not send the fields needed to do the work."""


@dataclass(frozen=True)
class PropertySubmission:
    property_details: str
    bedrooms: str
    location: str
    client_email: str
    event_id: str | None = None


def _clean_text(value: Any) -> str:
    """Convert Tally field values into readable text without leaking objects."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(_clean_text(item) for item in value if _clean_text(item))
    if isinstance(value, dict):
        if "value" in value:
            return _clean_text(value["value"])
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _normalize_label(value: Any) -> str:
    return " ".join(_clean_text(value).lower().replace("_", " ").replace("-", " ").split())


def _collect_fields(payload: dict[str, Any]) -> dict[str, str]:
    """Support Tally's fields array plus simple direct JSON test payloads."""
    fields: dict[str, str] = {}

    def add(label: Any, value: Any) -> None:
        normalized = _normalize_label(label)
        cleaned = _clean_text(value)
        if normalized and cleaned:
            fields[normalized] = cleaned

    for source in (payload, payload.get("data", {})):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if key != "fields" and not isinstance(value, (dict, list)):
                add(key, value)

        raw_fields = source.get("fields")
        if isinstance(raw_fields, list):
            for field in raw_fields:
                if isinstance(field, dict):
                    add(field.get("label") or field.get("key"), field.get("value"))
        elif isinstance(raw_fields, dict):
            for key, value in raw_fields.items():
                add(key, value)

    return fields


def _find_field(fields: dict[str, str], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        normalized_alias = _normalize_label(alias)
        if normalized_alias in fields:
            return fields[normalized_alias]

    for label, value in fields.items():
        if any(alias in label for alias in aliases):
            return value
    return ""


def parse_submission(payload: dict[str, Any]) -> PropertySubmission:
    if not isinstance(payload, dict):
        raise PayloadError("Webhook body must be a JSON object.")

    event_type = payload.get("eventType")
    if event_type and event_type != "FORM_RESPONSE":
        raise PayloadError(f"Ignoring unsupported Tally event type: {event_type}.")

    fields = _collect_fields(payload)
    property_details = _find_field(
        fields,
        ("property details", "property description", "description", "property"),
    )
    bedrooms = _find_field(fields, ("bedrooms", "bedroom", "number of beds", "beds"))
    location = _find_field(fields, ("location", "address", "city", "neighborhood", "area"))
    client_email = _find_field(fields, ("client email", "email", "e-mail", "contact email"))

    missing = [
        name
        for name, value in (
            ("property details", property_details),
            ("bedrooms", bedrooms),
            ("location", location),
            ("client email", client_email),
        )
        if not value
    ]
    if missing:
        raise PayloadError(f"Missing required form field(s): {', '.join(missing)}.")

    if "@" not in client_email or "." not in client_email.rsplit("@", 1)[-1]:
        raise PayloadError("The client email address is not valid.")

    data = payload.get("data")
    event_id = payload.get("eventId") or (
        data.get("submissionId") if isinstance(data, dict) else None
    )
    return PropertySubmission(
        property_details=property_details,
        bedrooms=bedrooms,
        location=location,
        client_email=client_email,
        event_id=event_id,
    )


def verify_tally_signature(raw_body: bytes) -> bool:
    """Verify Tally's HMAC signature when TALLY_WEBHOOK_SECRET is configured."""
    secret = os.getenv("TALLY_WEBHOOK_SECRET")
    if not secret:
        return True

    provided = request.headers.get("X-Tally-Signature") or request.headers.get("Tally-Signature")
    if not provided:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    provided_digest = provided.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided_digest)


def generate_captions(submission: PropertySubmission) -> list[str]:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY")
    if not api_key:
        raise ConfigurationError(
            "OPENAI_API_KEY is not configured. Add it in Replit Secrets before receiving submissions."
        )

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        response_format={"type": "json_object"},
        max_tokens=1400,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an elite luxury real-estate copywriter. Write sophisticated, "
                    "specific property marketing copy with a calm, confident, editorial voice. "
                    "Never invent amenities or facts. Avoid cliches, exclamation marks, emojis, "
                    "and claims of affiliation with Sotheby's International Realty. "
                    "Return exactly valid JSON in the shape {\"captions\": [\"...\", \"...\", \"...\"]}."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Create exactly three distinct property captions for social media or a "
                    "luxury listing campaign. Each caption should be 45–90 words and feel "
                    "Sotheby's-level: evocative, polished, and grounded in the supplied facts. "
                    "Give each a different editorial angle without adding unsupported details.\n\n"
                    f"Property details: {submission.property_details}\n"
                    f"Bedrooms: {submission.bedrooms}\n"
                    f"Location: {submission.location}"
                ),
            },
        ],
    )

    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise RuntimeError("OpenAI returned an empty caption response.")

    try:
        result = json.loads(content)
        captions = result["captions"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("OpenAI returned captions in an unexpected format.") from exc

    if (
        not isinstance(captions, list)
        or len(captions) != 3
        or not all(isinstance(caption, str) and caption.strip() for caption in captions)
    ):
        raise RuntimeError("OpenAI did not return exactly three usable captions.")
    return [caption.strip() for caption in captions]


def _caption_email_html(submission: PropertySubmission, captions: list[str]) -> str:
    caption_blocks = "".join(
        (
            f"<article style='margin:0 0 24px'>"
            f"<p style='margin:0 0 8px;color:#a98a55;font-size:12px;"
            f"letter-spacing:1.5px;text-transform:uppercase'>Caption {index}</p>"
            f"<p style='margin:0;line-height:1.7;color:#2d2924'>{html.escape(caption)}</p>"
            f"</article>"
        )
        for index, caption in enumerate(captions, start=1)
    )
    return f"""
    <div style="background:#f7f4ef;padding:36px 18px;font-family:Georgia,serif">
      <div style="max-width:640px;margin:0 auto;background:#fffdf9;padding:42px 38px">
        <p style="margin:0 0 10px;color:#a98a55;font:12px Arial,sans-serif;
          letter-spacing:2px;text-transform:uppercase">Global AI Captions</p>
        <h1 style="margin:0 0 8px;color:#24211e;font-size:28px;font-weight:normal">
          Your property captions
        </h1>
        <p style="margin:0 0 32px;color:#756d65;font:14px Arial,sans-serif">
          {html.escape(submission.location)} · {html.escape(submission.bedrooms)} bedrooms
        </p>
        {caption_blocks}
        <div style="border-top:1px solid #e5ded4;margin-top:28px;padding-top:18px">
          <p style="margin:0;color:#756d65;font:12px Arial,sans-serif">
            Prepared from the property details submitted through your form.
          </p>
        </div>
      </div>
    </div>
    """


def send_captions_email(submission: PropertySubmission, captions: list[str]) -> str:
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise ConfigurationError(
            "RESEND_API_KEY is not configured. Connect Resend or add the secret before receiving submissions."
        )

    sender = os.getenv("RESEND_FROM_EMAIL", "Global AI Captions <onboarding@resend.dev>")
    payload = {
        "from": sender,
        "to": [submission.client_email],
        "subject": f"Your property captions — {submission.location}",
        "html": _caption_email_html(submission, captions),
        "text": "\n\n".join(
            f"Caption {index}\n{caption}" for index, caption in enumerate(captions, start=1)
        ),
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if submission.event_id:
        headers["Idempotency-Key"] = f"tally-{submission.event_id}"

    response = requests.post(
        "https://api.resend.com/emails",
        headers=headers,
        json=payload,
        timeout=20,
    )
    if not response.ok:
        app.logger.error("Resend rejected the email: status=%s body=%s", response.status_code, response.text)
        raise RuntimeError("Resend could not deliver the captions email.")

    body = response.json()
    return str(body.get("id", "sent"))


@app.get("/")
def index():
    return jsonify(
        {
            "app": "global-ai-captions",
            "status": "ok",
            "webhook": "/webhook",
            "configuration": {
                "openai": bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY")),
                "resend": bool(os.getenv("RESEND_API_KEY")),
                "tally_signature_verification": bool(os.getenv("TALLY_WEBHOOK_SECRET")),
            },
        }
    )


@app.get("/healthz")
def healthz():
    configured = bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY")) and bool(
        os.getenv("RESEND_API_KEY")
    )
    return jsonify({"status": "ok" if configured else "degraded", "configured": configured}), (
        200 if configured else 503
    )


@app.post("/webhook")
def webhook():
    raw_body = request.get_data()
    if not verify_tally_signature(raw_body):
        return jsonify({"error": "Invalid Tally webhook signature."}), 401

    payload = request.get_json(silent=True)
    try:
        submission = parse_submission(payload)
        captions = generate_captions(submission)
        email_id = send_captions_email(submission, captions)
    except PayloadError as exc:
        return jsonify({"error": str(exc)}), 400
    except ConfigurationError as exc:
        app.logger.error("%s", exc)
        return jsonify({"error": str(exc)}), 503
    except Exception:
        app.logger.exception("Caption webhook processing failed.")
        return jsonify({"error": "Caption generation or email delivery failed."}), 502

    app.logger.info("Delivered three captions to %s", submission.client_email)
    return jsonify(
        {
            "status": "sent",
            "emailId": email_id,
            "captions": captions,
        }
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )