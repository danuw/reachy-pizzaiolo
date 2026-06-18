from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


def _orders_dir() -> Path:
    """Return the configured orders directory, defaulting to ./orders."""
    return Path(os.getenv("PIZZA_ORDERS_DIR", "orders")).expanduser().resolve()


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", value or "").strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:50] or "guest"


class CallForHelp(Tool):
    """Record that Reachy needs a human host to help with the order."""

    name = "call_for_help"
    description = (
        "Call for a human host when the ordering conversation is stuck, unsafe, disruptive, "
        "or when order checkout/file writing fails."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "customer_name": {
                "type": "string",
                "description": "Guest name if known.",
            },
            "reason": {
                "type": "string",
                "description": "Brief reason a host is needed.",
            },
            "urgency": {
                "type": "string",
                "enum": ["normal", "high"],
                "description": "Use high only for repeated disruption, alcohol refusal issues, or checkout failure.",
            },
        },
        "required": ["reason"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        customer_name = str(kwargs.get("customer_name", "")).strip() or "Unknown guest"
        reason = str(kwargs.get("reason", "")).strip()
        urgency = str(kwargs.get("urgency", "normal")).strip().lower()

        if urgency not in {"normal", "high"}:
            urgency = "normal"

        if not reason:
            reason = "Reachy Mini Pizzaiolo needs help with the order."

        now = datetime.now(timezone.utc)
        request_id = uuid.uuid4().hex[:8]
        help_dir = _orders_dir() / "help_requests"
        help_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "request_id": request_id,
            "created_at_utc": now.isoformat(),
            "customer_name": customer_name,
            "reason": reason,
            "urgency": urgency,
        }

        filename = f"help_{_safe_name(customer_name)}_{now.strftime('%Y%m%d_%H%M%S')}_{request_id}.json"
        path = help_dir / filename
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        return {
            "ok": True,
            "request_id": request_id,
            "file": str(path),
            "message": "A host help request has been recorded.",
        }
