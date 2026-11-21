#!/usr/bin/env python3
"""Seed a demo workspace with documents through the public API.

Runs with the Python standard library only, so it works both on the host and
inside the API container. The compose stack invokes it via the `seed` profile.

    python scripts/seed_demo.py
"""

import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1").rstrip("/")
EMAIL = os.environ.get("DEMO_EMAIL", "demo@example.com")
PASSWORD = os.environ.get("DEMO_PASSWORD", "DemoPassw0rd!")
WORKSPACE_NAME = "Demo workspace"
WORKSPACE_SLUG = "demo"

DOCUMENTS = {
    "handbook.txt": (
        "Northwind Labs employee handbook\n\n"
        "Day one starts at 09:00 at the reception desk on floor two. "
        "Bring a photo ID. Your badge is issued by Facilities.\n\n"
        "Paid time off accrues at 1.75 days per month and is capped at 25 days. "
        "Parental leave is 16 weeks at full pay for primary caregivers.\n\n"
        "Security incidents must be reported within 24 hours to "
        "security@northwind.example. Multi-factor authentication uses hardware keys.\n"
    ),
    "expenses.txt": (
        "Travel and expenses\n\n"
        "Book flights at least 14 days in advance. Economy class is the default "
        "for trips under six hours. The preferred airline is Skyline Air.\n\n"
        "Hotels are capped at 180 USD per night, or 240 USD in New York and "
        "San Francisco. Meals are capped at 60 USD per day with receipts.\n\n"
        "Submit expense reports within 30 days. Receipts are required for "
        "single items above 25 USD.\n"
    ),
    "support.txt": (
        "Service desk guide\n\n"
        "If the VPN client fails at 40 percent, restart the service and reconnect "
        "using the Frankfurt gateway. The Sydney gateway is reserved for APAC.\n\n"
        "A full mailbox quota of 10 GB is the usual cause of missing email. "
        "Empty the deleted folder or ask the desk for more space.\n\n"
        "Call the service desk at ext 4357 or email desk@northwind.example. "
        "For a cracked screen, request an exchange rather than a repair.\n"
    ),
}


class SeedError(RuntimeError):
    pass


def request(
    method: str,
    path: str,
    token: str | None = None,
    body: dict | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
) -> dict:
    payload = (
        data
        if data is not None
        else (json.dumps(body).encode() if body is not None else None)
    )
    req = urllib.request.Request(BASE + path, data=payload, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if content_type:
        req.add_header("Content-Type", content_type)
    elif body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise SeedError(
            f"{method} {path}: HTTP {exc.code} {exc.read().decode()[:300]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SeedError(
            f"{method} {path}: cannot reach {BASE} ({exc.reason}). "
            "Is the API container healthy?"
        ) from exc
    return json.loads(raw) if raw else {}


def multipart(filename: str, content: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode()
        + content.encode()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return body, f"multipart/form-data; boundary={boundary}"


def main() -> None:
    # Register is idempotent from the seeder's point of view.
    try:
        request("POST", "/auth/register", body={"email": EMAIL, "password": PASSWORD})
    except SeedError as exc:
        if "409" not in str(exc):
            raise
    token = request("POST", "/auth/login", body={"email": EMAIL, "password": PASSWORD})[
        "access_token"
    ]

    workspaces = request("GET", "/workspaces", token=token)
    existing = next(
        (item for item in workspaces if item["slug"] == WORKSPACE_SLUG), None
    )
    if existing:
        workspace_id = existing["id"]
        print(f"Reusing workspace {workspace_id}")
    else:
        workspace_id = request(
            "POST",
            "/workspaces",
            token=token,
            body={"name": WORKSPACE_NAME, "slug": WORKSPACE_SLUG},
        )["id"]
        print(f"Created workspace {workspace_id}")

    for filename, content in DOCUMENTS.items():
        data, content_type = multipart(filename, content)
        try:
            request(
                "POST",
                f"/workspaces/{workspace_id}/documents",
                token=token,
                data=data,
                content_type=content_type,
            )
            print(f"Uploaded {filename}")
        except SeedError as exc:
            if "DUPLICATE_DOCUMENT" not in str(exc):
                raise
            print(f"Already uploaded {filename}")

    deadline = time.monotonic() + 180
    while True:
        listing = request("GET", f"/workspaces/{workspace_id}/documents", token=token)
        statuses = [item["status"] for item in listing["items"]]
        if statuses and all(status == "ready" for status in statuses):
            break
        if "failed" in statuses:
            raise SeedError(f"a demo document failed to ingest: {statuses}")
        if time.monotonic() > deadline:
            raise SeedError(f"documents did not become ready in time: {statuses}")
        time.sleep(2)

    web = os.environ.get("WEB_URL", "http://localhost")
    print("\nDemo ready.")
    print(f"  URL:      {web}/workspaces/{workspace_id}/chat")
    print(f"  Email:    {EMAIL}")
    print(f"  Password: {PASSWORD}")
    print("\nAsk: 'What is the VPN gateway?' or 'How much is the hotel allowance?'")


if __name__ == "__main__":
    main()
