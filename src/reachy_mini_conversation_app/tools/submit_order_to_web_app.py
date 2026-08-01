from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


MENU_ITEMS = {
    "The Zekey": "Pizza",
    "The Neroli": "Pizza",
    "The Dan": "Pizza",
    "Coca Cola": "Drink",
    "Diet Coke": "Drink",
    "Apple juice": "Drink",
    "Sprite": "Drink",
    "Cola Cao": "Drink",
    "Pimm's": "Drink",
    "Water": "Drink",
}

ITEM_ALIASES = {
    "apple juice": "Apple juice",
    "apple juce": "Apple juice",
    "apple huice": "Apple juice",
    "sprite": "Sprite",
    "cola cao": "Cola Cao",
    "colacao": "Cola Cao",
    "coca cola": "Coca Cola",
    "coke": "Coca Cola",
    "diet coke": "Diet Coke",
    "pimms": "Pimm's",
    "pimm's": "Pimm's",
    "water": "Water",
    "zekey": "The Zekey",
    "the zekey": "The Zekey",
    "neroli": "The Neroli",
    "the neroli": "The Neroli",
    "dan": "The Dan",
    "the dan": "The Dan",
    "margherita": "The Zekey",
    "zekey margherita": "The Zekey",
    "margherita with olives": "The Neroli",
    "neroli margherita": "The Neroli",
    "tuna pizza": "The Dan",
}

OUT_OF_STOCK = {"The Allegra"}


def _is_waiting_order_id(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"", "waiting", "none", "null"}


def _terminal_base_url() -> str:
    raw = os.getenv("TERMINAL_BASE_URL", "http://192.168.68.147").strip().rstrip("/")
    parsed = urlparse(raw)
    if not parsed.scheme:
        return f"http://{raw}"
    return raw


def _terminal_timeout_seconds() -> float:
    return float(os.getenv("TERMINAL_TIMEOUT_SECONDS", "5"))


def _terminal_request_json(method: str, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = _terminal_base_url() + path
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=_terminal_timeout_seconds()) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _best_effort_reset_terminal_checkout(customer_name: str, order_id: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"attempted": True, "ok": False}

    try:
        health = _terminal_request_json("GET", "/health")
    except Exception as exc:
        result["error"] = f"terminal health unavailable: {type(exc).__name__}: {exc}"
        return result

    expected_version = health.get("version") if isinstance(health.get("version"), int) else None
    terminal_order_id = str(health.get("order_id") or "").strip()
    selected_order_id = str(order_id or terminal_order_id).strip()

    try:
        confirm_payload: Dict[str, Any] = {"confirm": True}
        if customer_name:
            confirm_payload["customer_name"] = customer_name
        _terminal_request_json("POST", "/ui/checkout/confirm", confirm_payload)
    except Exception:
        pass

    complete_payload: Dict[str, Any] = {
        "operation": "complete",
        "age_verified_for_alcohol": False,
    }
    if expected_version is not None:
        complete_payload["expected_version"] = expected_version
    if selected_order_id and not _is_waiting_order_id(selected_order_id):
        complete_payload["order_id"] = selected_order_id

    try:
        response = _terminal_request_json("POST", "/payload", complete_payload)
        result["ok"] = True
        result["response"] = response
    except Exception as exc:
        result["error"] = f"terminal reset failed: {type(exc).__name__}: {exc}"

    return result


def _normalise_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    raw_name = str(raw.get("name", "")).strip()
    name = ITEM_ALIASES.get(raw_name.lower(), raw_name)

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


def _dashboard_url_from_api(api_url: str) -> str:
    parsed = urlparse(api_url)
    if not parsed.scheme or not parsed.netloc:
        return api_url
    return f"{parsed.scheme}://{parsed.netloc}/"


class SubmitOrderToWebApp(Tool):
    """Submit a confirmed final pizza order to the order web app."""

    name = "submit_order_to_web_app"
    description = (
        "Submit a confirmed final restaurant order to the order web app API. "
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
                "error": "Order was not submitted because confirmed was not true.",
            }

        if not customer_name:
            return {
                "ok": False,
                "error": "Order was not submitted because customer_name is missing.",
            }

        if not isinstance(raw_items, list) or not raw_items:
            return {
                "ok": False,
                "error": "Order was not submitted because the basket is empty.",
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
        order = {
            "order_id": kwargs.get("order_id") or uuid.uuid4().hex[:8],
            "created_at_utc": now.isoformat(),
            "customer_name": customer_name,
            "items": items,
            "order_summary": order_summary,
            "age_verified_for_alcohol": age_verified_for_alcohol,
        }

        api_url = os.getenv("ORDER_WEB_APP_URL", "http://127.0.0.1:8787/api/orders").strip()
        timeout_seconds = float(os.getenv("ORDER_WEB_APP_TIMEOUT_SECONDS", "5"))

        req = urllib.request.Request(
            api_url,
            data=json.dumps(order).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8")
            payload = json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {
                "ok": False,
                "error": f"Order web app rejected request ({exc.code}): {body}",
            }
        except urllib.error.URLError as exc:
            return {
                "ok": False,
                "error": f"Order web app is unreachable at {api_url}: {exc.reason}",
            }
        except TimeoutError:
            return {
                "ok": False,
                "error": f"Timed out while contacting order web app at {api_url}.",
            }
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": "Order web app returned invalid JSON.",
            }

        accepted_order_id = str(payload.get("order_id") or order["order_id"])
        terminal_reset = _best_effort_reset_terminal_checkout(customer_name, accepted_order_id)

        return {
            "ok": True,
            "order_id": accepted_order_id,
            "web_app_url": _dashboard_url_from_api(api_url),
            "terminal_checkout_reset": terminal_reset,
            "message": f"Order submitted for {customer_name}.",
        }
