"""Same-language and cross-language retrieval probes.

Run against a live API with a multilingual profile active:

    uv run python evals/multilingual.py http://localhost:8000/api/v1 \
        demo@example.com DemoPassw0rd!

The script reports recall@3 per query; it does not modify data.
"""

from __future__ import annotations

import json
import sys
import urllib.request

CASES = [
    ("en", "What is the hotel allowance?", "expenses"),
    ("es", "¿Cuál es el límite del hotel?", "expenses"),
    ("fr", "Quel est le plafond de l'hôtel ?", "expenses"),
    ("en", "How do I reset the VPN client?", "support"),
    ("de", "Wie setze ich den VPN-Client zurück?", "support"),
]


def _post(url: str, body: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> int:
    base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000/api/v1"
    email = sys.argv[2] if len(sys.argv) > 2 else "demo@example.com"
    password = sys.argv[3] if len(sys.argv) > 3 else "DemoPassw0rd!"
    token = _post(f"{base}/auth/login", {"email": email, "password": password})[
        "access_token"
    ]
    workspaces = json.load(
        urllib.request.urlopen(
            urllib.request.Request(f"{base}/workspaces", headers={"Authorization": f"Bearer {token}"})
        )
    )
    workspace_id = workspaces[0]["id"]
    hits = 0
    for language, query, expected in CASES:
        response = _post(
            f"{base}/workspaces/{workspace_id}/search", {"query": query}, token
        )
        filenames = [item["filename"] for item in response["items"][:3]]
        matched = any(expected in name.lower() for name in filenames)
        hits += int(matched)
        print(f"{language}: {query!r} -> {filenames} ({'hit' if matched else 'miss'})")
    print(f"recall@3: {hits}/{len(CASES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
