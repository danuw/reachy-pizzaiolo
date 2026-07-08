from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
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
    "margherita with olives": "The Neroli",
}

OUT_OF_STOCK = {"The Allegra"}
PAYLOAD_OPS = {
    "add",
    "replace",
    "remove",
    "clear",
    "delete_line",
    "adjust_line",
    "checkout",
    "complete",
    "undo",
}


def _is_waiting_order_id(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"", "waiting", "none", "null"}


def _base_url() -> str:
    raw = os.getenv("TERMINAL_BASE_URL", "http://192.168.68.147").strip().rstrip("/")
    parsed = urlparse(raw)
    if not parsed.scheme:
        return f"http://{raw}"
    return raw


def _timeout_seconds() -> float:
    return float(os.getenv("TERMINAL_TIMEOUT_SECONDS", "5"))


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


def _request_json(method: str, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = _base_url() + path
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=_timeout_seconds()) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _best_effort_health() -> Dict[str, Any]:
    try:
        return _request_json("GET", "/health")
    except Exception:
        return {}


class SyncOrderToTerminal(Tool):
    """Sync ongoing order state with the E1003 terminal over HTTP."""

    name = "sync_order_to_terminal"
    description = (
        "Sync in-progress restaurant orders with the E1003 terminal server at /payload, "
        "and drive checkout prompts/decision flow. Use this throughout ordering, not just at checkout."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "description": (
                    "Operation type: payload ops (add, replace, remove, clear, delete_line, adjust_line, checkout, complete, undo), "
                    "or UI ops prompt_checkout, confirm_checkout, wait_checkout_result, or health."
                ),
            },
            "expected_version": {
                "type": "integer",
                "description": "Optional optimistic sync version from GET /health.",
            },
            "order_id": {
                "type": "string",
                "description": "Current order id to track on terminal.",
            },
            "customer_name": {
                "type": "string",
                "description": "Current customer name.",
            },
            "items": {
                "type": "array",
                "description": "Order items with category, name, quantity, and notes.",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "name": {"type": "string"},
                        "quantity": {"type": "integer"},
                        "notes": {"type": "string"},
                    },
                },
            },
            "order_summary": {
                "type": "string",
                "description": "Short order summary sentence.",
            },
            "age_verified_for_alcohol": {
                "type": "boolean",
                "description": "Alcohol verification state.",
            },
            "line_id": {
                "type": "string",
                "description": "Line id for delete_line/adjust_line operations.",
            },
            "delta": {
                "type": "integer",
                "description": "Delta for adjust_line operations.",
            },
            "confirm": {
                "type": "boolean",
                "description": "Used by confirm_checkout operation.",
            },
            "wait_timeout_seconds": {
                "type": "number",
                "description": "Only for wait_checkout_result. How long to poll /health for customer decision.",
            },
        },
        "required": ["operation"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        operation = str(kwargs.get("operation", "")).strip().lower()

        if not operation:
            return {"ok": False, "error": "operation is required."}

        if operation == "health":
            try:
                health = _request_json("GET", "/health")
                return {"ok": True, "operation": operation, "health": health}
            except urllib.error.URLError as exc:
                return {"ok": False, "error": f"Terminal is unreachable at {_base_url()}: {exc.reason}"}
            except Exception as exc:
                return {"ok": False, "error": f"health failed: {type(exc).__name__}: {exc}"}

        if operation == "prompt_checkout":
            try:
                response = _request_json("POST", "/ui/checkout/prompt", {})
                return {"ok": True, "operation": operation, "response": response}
            except urllib.error.URLError as exc:
                return {"ok": False, "error": f"Terminal is unreachable at {_base_url()}: {exc.reason}"}
            except Exception as exc:
                return {"ok": False, "error": f"prompt_checkout failed: {type(exc).__name__}: {exc}"}

        if operation == "confirm_checkout":
            confirm = bool(kwargs.get("confirm", False))
            customer_name = str(kwargs.get("customer_name", "")).strip()
            payload: Dict[str, Any] = {"confirm": confirm}
            if customer_name:
                payload["customer_name"] = customer_name
            try:
                response = _request_json("POST", "/ui/checkout/confirm", payload)
                return {"ok": True, "operation": operation, "response": response}
            except urllib.error.URLError as exc:
                return {"ok": False, "error": f"Terminal is unreachable at {_base_url()}: {exc.reason}"}
            except Exception as exc:
                return {"ok": False, "error": f"confirm_checkout failed: {type(exc).__name__}: {exc}"}

        if operation == "wait_checkout_result":
            try:
                baseline = _best_effort_health()
                baseline_version = baseline.get("version")
                baseline_order_id = str(
                    kwargs.get("order_id")
                    or baseline.get("order_id")
                    or ""
                ).strip()

                timeout = float(
                    kwargs.get("wait_timeout_seconds")
                    or os.getenv("TERMINAL_CHECKOUT_WAIT_TIMEOUT_SECONDS", "25")
                )
                deadline = asyncio.get_event_loop().time() + max(1.0, timeout)

                while asyncio.get_event_loop().time() < deadline:
                    health = _request_json("GET", "/health")
                    version = health.get("version")
                    done = bool(health.get("done", False))
                    current_order_id = str(health.get("order_id") or "").strip()

                    if done:
                        return {
                            "ok": True,
                            "operation": operation,
                            "checkout_result": "confirmed",
                            "health": health,
                        }

                    if not _is_waiting_order_id(baseline_order_id) and _is_waiting_order_id(current_order_id):
                        return {
                            "ok": True,
                            "operation": operation,
                            "checkout_result": "confirmed",
                            "health": health,
                        }

                    if (
                        isinstance(version, int)
                        and isinstance(baseline_version, int)
                        and version > baseline_version
                    ):
                        return {
                            "ok": True,
                            "operation": operation,
                            "checkout_result": "cancelled",
                            "health": health,
                        }

                    await asyncio.sleep(0.6)

                return {
                    "ok": True,
                    "operation": operation,
                    "checkout_result": "cancelled",
                    "health": _best_effort_health(),
                }
            except urllib.error.URLError as exc:
                return {"ok": False, "error": f"Terminal is unreachable at {_base_url()}: {exc.reason}"}
            except Exception as exc:
                return {"ok": False, "error": f"wait_checkout_result failed: {type(exc).__name__}: {exc}"}

        if operation not in PAYLOAD_OPS:
            return {"ok": False, "error": f"Unsupported operation '{operation}'."}

        raw_items = kwargs.get("items", [])
        items: List[Dict[str, Any]] = []
        if raw_items:
            if not isinstance(raw_items, list):
                return {"ok": False, "error": "items must be a list."}
            try:
                items = [_normalise_item(item) for item in raw_items]
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}

        if any(item["name"] == "Pimm's" for item in items):
            age_verified = bool(kwargs.get("age_verified_for_alcohol", False))
            if not age_verified:
                return {
                    "ok": False,
                    "error": "Order includes Pimm's but age verification was not confirmed.",
                }

        expected_version_raw = kwargs.get("expected_version")
        expected_version = int(expected_version_raw) if isinstance(expected_version_raw, int) else None
        if expected_version is None:
            health = _best_effort_health()
            if isinstance(health.get("version"), int):
                expected_version = int(health["version"])

        payload: Dict[str, Any] = {
            "operation": operation,
        }
        if expected_version is not None:
            payload["expected_version"] = expected_version

        order_id = str(kwargs.get("order_id", "")).strip()
        if order_id:
            payload["order_id"] = order_id

        customer_name = str(kwargs.get("customer_name", "")).strip()
        if customer_name:
            payload["customer_name"] = customer_name

        if items:
            payload["items"] = items

        order_summary = str(kwargs.get("order_summary", "")).strip()
        if order_summary:
            payload["order_summary"] = order_summary

        payload["age_verified_for_alcohol"] = bool(kwargs.get("age_verified_for_alcohol", False))

        line_id = str(kwargs.get("line_id", "")).strip()
        if line_id:
            payload["line_id"] = line_id

        delta = kwargs.get("delta")
        if isinstance(delta, int):
            payload["delta"] = delta

        try:
            response = _request_json("POST", "/payload", payload)
            return {"ok": True, "operation": operation, "response": response}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 409:
                latest_health = _best_effort_health()
                latest_version = latest_health.get("version")
                if isinstance(latest_version, int):
                    payload["expected_version"] = latest_version
                    try:
                        response = _request_json("POST", "/payload", payload)
                        return {
                            "ok": True,
                            "operation": operation,
                            "response": response,
                            "version_retried": True,
                            "used_version": latest_version,
                        }
                    except Exception:
                        pass

            return {
                "ok": False,
                "error": f"Terminal rejected /payload ({exc.code}): {body}",
            }
        except urllib.error.URLError as exc:
            return {"ok": False, "error": f"Terminal is unreachable at {_base_url()}: {exc.reason}"}
        except Exception as exc:
            return {"ok": False, "error": f"payload sync failed: {type(exc).__name__}: {exc}"}
