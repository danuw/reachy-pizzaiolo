from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse


COMPLETE_REMOVAL_DELAY_SECONDS = 5


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _format_order_details(order: dict[str, Any]) -> str:
    lines = [
        f"Order ID: {order.get('order_id', '')}",
        f"Created UTC: {order.get('created_at_utc', '')}",
        f"Customer: {order.get('customer_name', '')}",
        "",
        "Items:",
    ]

    items = order.get("items")
    if not isinstance(items, list) or not items:
        lines.append("(no items)")
    else:
        for item in items:
            if not isinstance(item, dict):
                continue
            line = f"- {item.get('quantity', '')} x {item.get('name', '')} ({item.get('category', '')})"
            notes = str(item.get("notes", "")).strip()
            if notes:
                line += f" | notes: {notes}"
            lines.append(line)

    summary = str(order.get("order_summary", "")).strip()
    if summary:
        lines.extend(["", f"Summary: {summary}"])

    if bool(order.get("age_verified_for_alcohol", False)):
        lines.extend(["", "Age verification: true"])

    if bool(order.get("_is_completed", False)):
        seconds_left = int(order.get("_seconds_until_removal", 0))
        lines.extend(["", f"Status: Completed (removes in {seconds_left}s)"])

    return "\n".join(lines)


def render_page(orders: list[dict[str, Any]], selected_id: str | None) -> str:
    selected: dict[str, Any] | None = None
    if orders:
        if selected_id:
            selected = next((o for o in orders if str(o.get("order_id", "")) == selected_id), None)
        if selected is None:
            selected = orders[0]

    list_items: list[str] = []
    if not orders:
        list_items.append('<li class="empty">No orders yet.</li>')
    else:
        for order in orders:
            order_id = str(order.get("order_id", ""))
            customer_name = _escape_html(str(order.get("customer_name", "Unknown")))
            item_count = len(order.get("items", [])) if isinstance(order.get("items"), list) else 0
            active = " active" if selected and order_id == str(selected.get("order_id", "")) else ""
            href = "/?selected=" + quote(order_id)
            meta = _escape_html(f"{order_id} | {item_count} item(s)")
            if bool(order.get("_is_completed", False)):
                seconds_left = int(order.get("_seconds_until_removal", 0))
                status = _escape_html(f"Completed - removing in {seconds_left}s")
            else:
                status = ""
            action_html = ""
            if not bool(order.get("_is_completed", False)):
                action_html = (
                    '<form method="post" action="/complete-order" class="quick-complete">'
                    f'<input type="hidden" name="order_id" value="{_escape_html(order_id)}">'
                    '<button type="submit">Complete</button>'
                    "</form>"
                )
            list_items.append(
                f'<li class="order{active}"><div class="row"><a href="{href}"><div class="customer">{customer_name}</div><div class="meta">{meta}</div>'
                + (f'<div class="status">{status}</div>' if status else "")
                + f"</a>{action_html}</div></li>"
            )

    details_text = "Waiting for orders..."
    if selected:
        details_text = _escape_html(_format_order_details(selected))

    details_action = ""
    if selected and not bool(selected.get("_is_completed", False)):
        selected_order_id = _escape_html(str(selected.get("order_id", "")))
        details_action = (
            '<form method="post" action="/complete-order" class="details-complete">'
            f'<input type="hidden" name="order_id" value="{selected_order_id}">'
            '<button type="submit">Mark Complete</button>'
            "</form>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="2">
  <title>Order Dashboard</title>
  <style>
    :root {{
      --panel: #ffffff;
      --line: #d8dde3;
      --text: #202733;
      --muted: #677184;
      --accent: #1a73e8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      color: var(--text);
      background: linear-gradient(180deg, #f7f9fc 0%, #eef2f6 100%);
      min-height: 100vh;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 12px;
      padding: 12px;
      min-height: 100vh;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      overflow: hidden;
    }}
    .panel h1 {{
      margin: 0;
      padding: 12px;
      font-size: 16px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfe;
    }}
    .count {{ color: var(--muted); font-weight: 500; }}
    #order-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      max-height: calc(100vh - 62px);
      overflow: auto;
    }}
    #order-list li {{ border-bottom: 1px solid var(--line); }}
    #order-list .row {{ display: flex; align-items: center; gap: 8px; }}
    #order-list li a {{
      display: block;
      flex: 1;
      padding: 10px 12px;
      color: inherit;
      text-decoration: none;
    }}
    #order-list li a:hover {{ background: #f7faff; }}
    #order-list li.active a {{
      background: #eaf2ff;
      border-left: 3px solid var(--accent);
      padding-left: 9px;
    }}
    #order-list li.empty {{ padding: 10px 12px; color: var(--muted); }}
    #order-list .status {{ color: #2c6a37; font-size: 12px; margin-top: 4px; }}
    .customer {{ font-weight: 600; }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
    #details {{ padding: 14px; white-space: pre-wrap; line-height: 1.45; }}
    .quick-complete {{ padding-right: 10px; }}
    .quick-complete button,
    .details-complete button {{
      background: #1a73e8;
      color: #fff;
      border: 0;
      border-radius: 6px;
      padding: 7px 10px;
      cursor: pointer;
      font-size: 12px;
    }}
    .quick-complete button:hover,
    .details-complete button:hover {{ background: #1666cd; }}
    .details-complete {{ padding: 0 14px 14px; }}
    @media (max-width: 860px) {{
      .layout {{ grid-template-columns: 1fr; }}
      #order-list {{ max-height: 260px; }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <section class="panel">
      <h1>Incoming Orders <span class="count">({len(orders)})</span></h1>
      <ul id="order-list">{''.join(list_items)}</ul>
    </section>
    <section class="panel">
      <h1>Order Details</h1>
      <div id="details">{details_text}</div>
      {details_action}
    </section>
  </div>
</body>
</html>
"""


class OrderStore:
    def __init__(self, db_path: Path) -> None:
        self._lock = threading.Lock()
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connection(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path), timeout=5)

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    completed_at_epoch REAL,
                    purge_after_epoch REAL
                )
                """
            )
            existing_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(orders)").fetchall()
                if len(row) > 1
            }
            if "completed_at_epoch" not in existing_columns:
                conn.execute("ALTER TABLE orders ADD COLUMN completed_at_epoch REAL")
            if "purge_after_epoch" not in existing_columns:
                conn.execute("ALTER TABLE orders ADD COLUMN purge_after_epoch REAL")
            conn.commit()

    def add_order(self, order: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO orders (
                        order_id,
                        created_at_utc,
                        payload_json,
                        completed_at_epoch,
                        purge_after_epoch
                    )
                    VALUES (?, ?, ?, NULL, NULL)
                    """,
                    (
                        str(order.get("order_id", "")),
                        str(order.get("created_at_utc", "")),
                        json.dumps(order, ensure_ascii=False),
                    ),
                )
                conn.commit()
        return order

    def mark_completed(self, order_id: str) -> bool:
        if not order_id.strip():
            return False

        now_epoch = datetime.now(timezone.utc).timestamp()
        purge_epoch = now_epoch + COMPLETE_REMOVAL_DELAY_SECONDS

        with self._lock:
            with self._connection() as conn:
                result = conn.execute(
                    """
                    UPDATE orders
                    SET completed_at_epoch = ?, purge_after_epoch = ?
                    WHERE order_id = ?
                      AND (completed_at_epoch IS NULL OR purge_after_epoch IS NULL)
                    """,
                    (now_epoch, purge_epoch, order_id),
                )
                conn.commit()
                return result.rowcount > 0

    def all_orders(self) -> list[dict[str, Any]]:
        now_epoch = datetime.now(timezone.utc).timestamp()
        with self._lock:
            with self._connection() as conn:
                conn.execute(
                    """
                    DELETE FROM orders
                    WHERE purge_after_epoch IS NOT NULL
                      AND purge_after_epoch <= ?
                    """,
                    (now_epoch,),
                )
                rows = conn.execute(
                    """
                    SELECT payload_json, completed_at_epoch, purge_after_epoch
                    FROM orders
                    ORDER BY created_at_utc DESC, rowid DESC
                    """
                ).fetchall()
                conn.commit()

            result: list[dict[str, Any]] = []
            for row in rows:
                try:
                    payload = json.loads(row[0])
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    completed_at_epoch = row[1]
                    purge_after_epoch = row[2]
                    if completed_at_epoch is not None and purge_after_epoch is not None:
                        seconds_left = max(0, int(math.ceil(float(purge_after_epoch) - now_epoch)))
                        payload["_is_completed"] = True
                        payload["_seconds_until_removal"] = seconds_left
                    else:
                        payload["_is_completed"] = False
                        payload["_seconds_until_removal"] = 0
                    result.append(payload)
            return result


DEFAULT_DB_PATH = Path(
    os.getenv("ORDER_WEB_APP_DB", str(Path(__file__).resolve().parent / "orders" / "order_web_app.db"))
).expanduser().resolve()
STORE = OrderStore(DEFAULT_DB_PATH)


class OrderDashboardHandler(BaseHTTPRequestHandler):
    server_version = "OrderDashboard/1.0"

    def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _read_form_body(self) -> dict[str, str] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        data = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        result: dict[str, str] = {}
        for key, values in data.items():
            if values:
                result[key] = values[0]
        return result

    def _send_redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        if path in {"/", "/index.html"}:
            selected = query.get("selected", [None])[0]
            body = render_page(STORE.all_orders(), selected).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/orders":
            self._send_json({"ok": True, "orders": STORE.all_orders()})
            return

        self._send_json({"ok": False, "error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/complete-order":
            form = self._read_form_body()
            if form is None:
                self._send_json({"ok": False, "error": "Invalid form body."}, status=HTTPStatus.BAD_REQUEST)
                return
            order_id = str(form.get("order_id", "")).strip()
            if not order_id:
                self._send_json({"ok": False, "error": "order_id is required."}, status=HTTPStatus.BAD_REQUEST)
                return
            STORE.mark_completed(order_id)
            self._send_redirect("/?selected=" + quote(order_id))
            return

        if path != "/api/orders":
            self._send_json({"ok": False, "error": "Not found."}, status=HTTPStatus.NOT_FOUND)
            return

        payload = self._read_json_body()
        if payload is None:
            self._send_json({"ok": False, "error": "Invalid JSON body."}, status=HTTPStatus.BAD_REQUEST)
            return

        customer_name = str(payload.get("customer_name", "")).strip()
        items = payload.get("items")

        if not customer_name:
            self._send_json({"ok": False, "error": "customer_name is required."}, status=HTTPStatus.BAD_REQUEST)
            return

        if not isinstance(items, list) or not items:
            self._send_json({"ok": False, "error": "items must be a non-empty list."}, status=HTTPStatus.BAD_REQUEST)
            return

        order = {
            "order_id": str(payload.get("order_id") or uuid.uuid4().hex[:8]),
            "created_at_utc": str(payload.get("created_at_utc") or datetime.now(timezone.utc).isoformat()),
            "customer_name": customer_name,
            "items": items,
            "order_summary": str(payload.get("order_summary", "")).strip(),
            "age_verified_for_alcohol": bool(payload.get("age_verified_for_alcohol", False)),
        }

        STORE.add_order(order)
        self._send_json({"ok": True, "order_id": order["order_id"]}, status=HTTPStatus.CREATED)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the simple order dashboard web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), OrderDashboardHandler)
    print(f"Order web app running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
