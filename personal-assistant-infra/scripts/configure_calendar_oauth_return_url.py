"""Configure Calendar OAuth2 return URLs on an Agent Identity workload identity."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from huaweicloudsdkagentidentity.v1 import (
    AgentIdentityClient,
    GetWorkloadIdentityRequest,
    UpdateWorkloadIdentityReqBody,
    UpdateWorkloadIdentityRequest,
)
from huaweicloudsdkagentidentity.v1.region.agentidentity_region import (
    AgentIdentityRegion,
)
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkcore.exceptions.exceptions import SdkException
from huaweicloudsdkcore.utils.http_utils import sanitize_for_serialization

DEFAULT_REGION = "cn-southwest-2"
DEFAULT_WORKLOAD_IDENTITY_NAME = "agent-personal-assistant"

AK_ENV_NAMES = ("HUAWEICLOUD_SDK_AK", "HUAWEICLOUD_AK", "HW_ACCESS_KEY")
SK_ENV_NAMES = ("HUAWEICLOUD_SDK_SK", "HUAWEICLOUD_SK", "HW_SECRET_KEY")
SECURITY_TOKEN_ENV_NAMES = (
    "HUAWEICLOUD_SDK_SECURITY_TOKEN",
    "HUAWEICLOUD_SECURITY_TOKEN",
    "HW_SECURITY_TOKEN",
)


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return None


def _required_env(names: tuple[str, ...], label: str) -> str:
    value = _first_env(names)
    if value:
        return value
    names_text = ", ".join(names)
    raise RuntimeError(f"Missing {label}. Set one of: {names_text}")


def _build_credentials() -> BasicCredentials:
    credentials = BasicCredentials(
        _required_env(AK_ENV_NAMES, "Huawei Cloud AK"),
        _required_env(SK_ENV_NAMES, "Huawei Cloud SK"),
    )
    security_token = _first_env(SECURITY_TOKEN_ENV_NAMES)
    if security_token:
        credentials.with_security_token(security_token)
    return credentials


def _build_client(region: str, endpoint: str | None) -> AgentIdentityClient:
    builder = AgentIdentityClient.new_builder().with_credentials(_build_credentials())
    builder.with_region(AgentIdentityRegion.value_of(region))
    if endpoint:
        builder.with_endpoint(endpoint)
    return builder.build()


def _as_dict(value: Any) -> dict[str, Any]:
    serialized = sanitize_for_serialization(value)
    return serialized if isinstance(serialized, dict) else {}


def _current_allowed_urls(
    client: AgentIdentityClient,
    workload_identity_name: str,
) -> list[str]:
    response = client.get_workload_identity(
        GetWorkloadIdentityRequest(workload_identity_name=workload_identity_name)
    )
    identity = _as_dict(response).get("workload_identity") or {}
    urls = identity.get("allowed_resource_oauth2_return_urls") or []
    return [url for url in urls if isinstance(url, str) and url]


def _dedupe_urls(urls: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Set Calendar OAuth2 return URLs on an Agent Identity workload "
            "identity. Defaults to dry-run."
        )
    )
    parser.add_argument(
        "--workload-identity-name",
        default=os.getenv(
            "AGENT_IDENTITY_WORKLOAD_NAME",
            DEFAULT_WORKLOAD_IDENTITY_NAME,
        ),
        help=(
            "Workload identity name. Defaults to "
            f"{DEFAULT_WORKLOAD_IDENTITY_NAME}."
        ),
    )
    parser.add_argument(
        "--return-url",
        action="append",
        default=[],
        help=(
            "Desired OAuth2 return URL to allow. Can be passed multiple "
            "times. Defaults to OAUTH2_CALENDAR_CALLBACK_URL when set. "
            "The final list fully replaces the remote allowlist."
        ),
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AGENT_IDENTITY_REGION", DEFAULT_REGION),
        help=f"Agent Identity region. Defaults to {DEFAULT_REGION}.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("AGENT_IDENTITY_ENDPOINT"),
        help="Optional Agent Identity endpoint override.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually update the workload identity. Without this, dry-run only.",
    )
    parser.add_argument(
        "--list-current",
        action="store_true",
        help=(
            "Print the current allowed return URLs and exit without comparing "
            "or updating."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    desired_urls = list(args.return_url)
    env_return_url = os.getenv("OAUTH2_CALENDAR_CALLBACK_URL")
    if env_return_url:
        desired_urls.append(env_return_url.strip())
    desired_urls = _dedupe_urls([url for url in desired_urls if url])

    if not args.list_current and not desired_urls:
        print(
            "No return URL provided. Set OAUTH2_CALENDAR_CALLBACK_URL or pass "
            "--return-url.",
            file=sys.stderr,
        )
        return 1

    try:
        client = _build_client(region=args.region, endpoint=args.endpoint)
        current_urls = _current_allowed_urls(client, args.workload_identity_name)
    except (RuntimeError, SdkException, KeyError) as exc:
        print(f"Failed to read workload identity: {exc}", file=sys.stderr)
        return 1

    print(f"Workload identity: {args.workload_identity_name}")
    print(f"Current allowed return URLs: {len(current_urls)}")
    for url in current_urls:
        print(f"  - {url}")

    if args.list_current:
        return 0

    print(f"Desired allowed return URLs: {len(desired_urls)}")
    for url in desired_urls:
        print(f"  = {url}")

    if current_urls == desired_urls:
        print("No update needed; allowed return URLs already match desired state.")
        return 0

    print("Remote allowlist will be replaced with the desired list above.")

    if not args.apply:
        print("Dry-run only. Re-run with --apply to update Agent Identity.")
        return 0

    try:
        client.update_workload_identity(
            UpdateWorkloadIdentityRequest(
                workload_identity_name=args.workload_identity_name,
                body=UpdateWorkloadIdentityReqBody(
                    allowed_resource_oauth2_return_urls=desired_urls
                ),
            )
        )
    except SdkException as exc:
        print(f"Failed to update workload identity: {exc}", file=sys.stderr)
        return 1

    print("Updated allowed_resource_oauth2_return_urls successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
