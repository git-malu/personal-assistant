"""List Agent Identity workload identities visible to the current credentials."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from huaweicloudsdkagentidentity.v1 import ListWorkloadIdentitiesRequest
from huaweicloudsdkcore.exceptions.exceptions import SdkException

from agent_identity_common import (
    DEFAULT_REGION,
    as_dict,
    build_client,
    sdk_exception_text,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "List Agent Identity workload identities in a region. This is a "
            "read-only troubleshooting helper."
        )
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"Agent Identity region. Defaults to {DEFAULT_REGION}.",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="Optional Agent Identity endpoint override.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Page size for list_workload_identities. Defaults to 100.",
    )
    return parser.parse_args()


def _created_by_text(identity: dict[str, Any]) -> str:
    created_by = identity.get("created_by") or {}
    if not isinstance(created_by, dict):
        return ""
    created_type = created_by.get("type") or ""
    identifier = created_by.get("identifier") or ""
    if created_type and identifier:
        return f"{created_type} {identifier}"
    return str(created_type or identifier)


def _list_identities(region: str, endpoint: str | None, limit: int):
    client = build_client(region=region, endpoint=endpoint)
    marker = None
    while True:
        response = client.list_workload_identities(
            ListWorkloadIdentitiesRequest(limit=limit, marker=marker)
        )
        data = as_dict(response)
        for identity in data.get("workload_identities") or []:
            if isinstance(identity, dict):
                yield identity
        page_info = data.get("page_info") or {}
        marker = page_info.get("next_marker") if isinstance(page_info, dict) else None
        if not marker:
            break


def main() -> int:
    args = _parse_args()
    try:
        identities = list(
            _list_identities(
                region=args.region,
                endpoint=args.endpoint,
                limit=args.limit,
            )
        )
    except (RuntimeError, SdkException) as exc:
        message = sdk_exception_text(exc) if isinstance(exc, SdkException) else str(exc)
        print(f"Failed to list workload identities: {message}", file=sys.stderr)
        return 1

    print(f"Region: {args.region}")
    print(f"Workload identities: {len(identities)}")
    for identity in identities:
        print(
            "  - "
            f"name={identity.get('name', '')} "
            f"authorizer_type={identity.get('authorizer_type', '')} "
            f"created_by={_created_by_text(identity)} "
            f"urn={identity.get('urn', '')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
