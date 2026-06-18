from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


MENU_ITEMS = {
    "The Zekey": "Pizza",
    "The Neroli": "Pizza",
    "The Dan": "Pizza",
    "Coca Cola": "Drink",
    "Diet Coke": "Drink",
    "Pimm's": "Drink",
    "Water": "Drink",
}

OUT_OF_STOCK = {"The Allegra"}


def _orders_dir() -> Path:
    """Return the configured orders directory, defaulting to ./orders."""
    return Path(os.getenv("PIZZA_ORDERS_DIR", "orders")).expanduser().resolve()


def _safe_name(value: str) -> str:
    """Create a filesystem-safe filename fragment from a customer's name."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", value or "").strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:50] or "guest"


def _normalise_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalise one order item."""
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ValueError("Every item must include a name.")

    if name in OUT_OF_STOCK:
        raise ValueError(f"{name} is out of stock and cannot be submitted.")

    if name not in MENU_ITEMS:
        raise ValueError(f"{name} is not on the approved menu.")

    try:
        quantity = int(raw.get("quantity", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Quantity for {name} must be a whole number.") from exc

    if quantity < 1 or quantity > 20:
        raise ValueError(f"Quantity for {name} must be between 1 and 20.")

    category = str(raw.get("category") or MENU_ITEMS[name]).strip()
    notes = str(raw.get("notes", "")).strip()

    return {
        "category": category,
        "name": name,
        "quantity": quantity,
        "notes": notes,
    }


class WriteFinalOrderFile(Tool):
    """Write a confirmed final pizza order to the local orders folder."""

    name = "write_final_order_file"
    description = (
        "Write a confirmed final restaurant order to a local orders folder. "
        "Use only after the guest has explicitly confirmed the final basket."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "customer_name": {
                "type": "string",
                "description": "Name the order should be stored under.",
            },
            "items": {
                "type": "array",
                "description": "Confirmed basket items.",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "Pizza, Drink, or other approved category.",
                        },
                        "name": {
                            "type": "string",
                            "description": "Canonical menu item name, for example The Zekey.",
                        },
                        "quantity": {
                            "type": "integer",
                            "description": "Quantity ordered.",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Optional customisation or clarification.",
                        },
                    },
                    "required": ["name", "quantity"],
                },
            },
            "order_summary": {
                "type": "string",
                "description": "Short natural language recap of the final order.",
            },
            "confirmed": {
                "type": "boolean",
                "description": "Must be true only when the guest has confirmed checkout.",
            },
            "age_verified_for_alcohol": {
                "type": "boolean",
                "description": "True only when Pimm's is included and the guest confirmed they are 18 or over.",
            },
        },
        "required": ["customer_name", "items", "confirmed"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        customer_name = str(kwargs.get("customer_name", "")).strip()
        confirmed = bool(kwargs.get("confirmed", False))
        raw_items = kwargs.get("items", [])
        order_summary = str(kwargs.get("order_summary", "")).strip()
        age_verified_for_alcohol = bool(kwargs.get("age_verified_for_alcohol", False))

        if not confirmed:
            return {
                "ok": False,
                "error": "Order was not written because confirmed was not true.",
            }

        if not customer_name:
            return {
                "ok": False,
                "error": "Order was not written because customer_name is missing.",
            }

        if not isinstance(raw_items, list) or not raw_items:
            return {
                "ok": False,
                "error": "Order was not written because the basket is empty.",
            }

        try:
            items: List[Dict[str, Any]] = [_normalise_item(item) for item in raw_items]
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        contains_pimms = any(item["name"] == "Pimm's" for item in items)
        if contains_pimms and not age_verified_for_alcohol:
            return {
                "ok": False,
                "error": "Order includes Pimm's but age verification was not confirmed.",
            }

        now = datetime.now(timezone.utc)
        order_id = uuid.uuid4().hex[:8]
        safe_customer_name = _safe_name(customer_name)
        orders_dir = _orders_dir()
        orders_dir.mkdir(parents=True, exist_ok=True)

        order = {
            "order_id": order_id,
            "created_at_utc": now.isoformat(),
            "customer_name": customer_name,
            "items": items,
            "order_summary": order_summary,
            "age_verified_for_alcohol": age_verified_for_alcohol,
        }

        timestamp = now.strftime("%Y%m%d_%H%M%S")
        base_filename = f"{safe_customer_name}_{timestamp}_{order_id}"
        json_path = orders_dir / f"{base_filename}.json"
        txt_path = orders_dir / f"{base_filename}.txt"

        json_path.write_text(json.dumps(order, indent=2, ensure_ascii=False), encoding="utf-8")

        lines = [
            f"Order ID: {order_id}",
            f"Name: {customer_name}",
            f"Created UTC: {now.isoformat()}",
            "",
            "Items:",
        ]
        for item in items:
            line = f"- {item['quantity']} x {item['name']} ({item['category']})"
            if item.get("notes"):
                line += f" — {item['notes']}"
            lines.append(line)

        if order_summary:
            lines.extend(["", f"Summary: {order_summary}"])

        txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        return {
            "ok": True,
            "order_id": order_id,
            "json_file": str(json_path),
            "txt_file": str(txt_path),
            "message": f"Order written for {customer_name}.",
        }
