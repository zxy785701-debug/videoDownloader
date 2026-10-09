"""Operator diagnostics and recovery without unsafe 'clear pending order' switches."""
import argparse
import json

import stripe

from .main import create_app


def main():
    parser = argparse.ArgumentParser(description="SaveAny billing operator tool")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    recover = commands.add_parser("recover-order")
    recover.add_argument("--order", required=True)
    recover.add_argument("--session", required=True)
    args = parser.parse_args()
    service = create_app().state.service
    if args.command == "check":
        price = service.provider.price()
        valid = price.get("active") and price.get("type") == "one_time" and price.get("unit_amount") == 1990 and price.get("currency") == "cny" and price.get("livemode") == service.config.live
        print(json.dumps({"stripe_sdk": stripe.VERSION, "environment": service.config.environment, "simulated": service.config.provider == "mock", "price_valid": bool(valid)}, ensure_ascii=False))
        if not valid:
            raise SystemExit(1)
    else:
        value = service.provider.session(args.session)
        if value.get("metadata", {}).get("order_id") != args.order:
            raise SystemExit("Session metadata does not match order; nothing changed.")
        with service.store.connection() as db:
            order = db.execute("SELECT * FROM orders WHERE id=?", (args.order,)).fetchone()
        if not order:
            raise SystemExit("Unknown order; nothing changed.")
        service.validate_session(value, dict(order))
        service.apply_session(value)
        if value.get("url") and service.safe_checkout_url(value["url"]):
            with service.store.connection(write=True) as db:
                db.execute("UPDATE orders SET checkout_url=? WHERE id=?", (value["url"], args.order))
        print("Verified and reconciled. Refresh account status in SaveAny.")


if __name__ == "__main__":
    main()
