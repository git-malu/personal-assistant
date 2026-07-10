"""Ensure the customer-owned local JWT workload identity exists."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from agent_identity_common import (
    DEFAULT_REGION,
    as_dict,
    build_client,
    dedupe,
    sdk_exception_text,
    split_csv,
)
from huaweicloudsdkagentidentity.v1 import (
    AgentIdentityClient,
    AuthorizerConfiguration,
    AuthorizerType,
    CreateWorkloadIdentityReqBody,
    CreateWorkloadIdentityRequest,
    CustomJWTAuthorizerConfiguration,
    GetWorkloadIdentityAuthorizerConfigurationRequest,
    GetWorkloadIdentityRequest,
    UpdateWorkloadIdentityReqBody,
    UpdateWorkloadIdentityRequest,
)
from huaweicloudsdkcore.exceptions.exceptions import (
    ClientRequestException,
    SdkException,
)

DEFAULT_LOCAL_JWT_WORKLOAD_NAME = "pa-local-jwt-workload"
DEFAULT_ENTRA_TENANT_ID = "2a1d3739-88c5-4314-b921-acbeac0abbfa"
DEFAULT_ENTRA_CLIENT_ID = "3a99a511-926c-475c-b6bc-325a037f574d"
DEFAULT_RETURN_URLS = [
    "https://agentarts-personal-assistant.pages.dev/auth/callback/m365-calendar",
    "http://localhost:5173/auth/callback/m365-calendar",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create or verify the customer-owned CUSTOM_JWT workload identity "
            "used by local/manual JWT-mode WAT exchange. Defaults to dry-run."
        )
    )
    parser.add_argument(
        "--name",
        default=os.getenv(
            "AGENT_IDENTITY_LOCAL_JWT_WORKLOAD_NAME",
            DEFAULT_LOCAL_JWT_WORKLOAD_NAME,
        ),
        help=(
            "Local JWT workload identity name. Defaults to "
            f"{DEFAULT_LOCAL_JWT_WORKLOAD_NAME}."
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
        "--tenant-id",
        default=os.getenv("AGENT_IDENTITY_LOCAL_JWT_TENANT_ID"),
        help=(
            "Microsoft Entra tenant ID used to derive discovery URL when "
            "--discovery-url is omitted."
        ),
    )
    parser.add_argument(
        "--discovery-url",
        default=os.getenv("AGENT_IDENTITY_LOCAL_JWT_DISCOVERY_URL"),
        help="Explicit OIDC discovery URL for the CUSTOM_JWT authorizer.",
    )
    parser.add_argument(
        "--audience",
        action="append",
        default=None,
        help=(
            "Allowed JWT audience. Can be passed multiple times. Defaults to "
            "AGENT_IDENTITY_LOCAL_JWT_AUDIENCE, VITE_ENTRA_CLIENT_ID, or the "
            "project Entra client ID."
        ),
    )
    parser.add_argument(
        "--client",
        action="append",
        default=None,
        help=(
            "Allowed JWT client. Can be passed multiple times. Defaults to "
            "AGENT_IDENTITY_LOCAL_JWT_CLIENTS, otherwise empty. Leave this "
            "empty for Microsoft Entra id_tokens that only carry aud."
        ),
    )
    parser.add_argument(
        "--scope",
        action="append",
        default=None,
        help="Required JWT scope. Can be passed multiple times. Defaults to empty.",
    )
    parser.add_argument(
        "--return-url",
        action="append",
        default=None,
        help=(
            "Allowed OAuth2 return URL. Can be passed multiple times. Defaults "
            "to deployed and local Calendar callback URLs."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually create or update the workload identity.",
    )
    return parser.parse_args()


def _discovery_url(args: argparse.Namespace) -> str:
    if args.discovery_url:
        return args.discovery_url.strip()
    tenant_id = (
        args.tenant_id or os.getenv("VITE_ENTRA_TENANT_ID") or DEFAULT_ENTRA_TENANT_ID
    )
    return (
        "https://login.microsoftonline.com/"
        f"{tenant_id}/v2.0/.well-known/openid-configuration"
    )


def _audiences(args: argparse.Namespace) -> list[str]:
    if args.audience:
        return dedupe(args.audience)
    values = split_csv(os.getenv("AGENT_IDENTITY_LOCAL_JWT_AUDIENCE"))
    if not values:
        values = split_csv(os.getenv("VITE_ENTRA_CLIENT_ID"))
    if not values:
        values = [DEFAULT_ENTRA_CLIENT_ID]
    return dedupe(values)


def _clients(args: argparse.Namespace) -> list[str]:
    if args.client:
        return dedupe(args.client)
    return dedupe(split_csv(os.getenv("AGENT_IDENTITY_LOCAL_JWT_CLIENTS")))


def _scopes(args: argparse.Namespace) -> list[str]:
    if args.scope:
        return dedupe(args.scope)
    return dedupe(split_csv(os.getenv("AGENT_IDENTITY_LOCAL_JWT_SCOPES")))


def _return_urls(args: argparse.Namespace) -> list[str]:
    values = list(args.return_url or DEFAULT_RETURN_URLS)
    values.extend(split_csv(os.getenv("AGENT_IDENTITY_LOCAL_JWT_RETURN_URLS")))
    calendar_callback_url = os.getenv("OAUTH2_CALENDAR_CALLBACK_URL")
    if calendar_callback_url:
        values.append(calendar_callback_url)
    return dedupe(values)


def _desired_state(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "name": args.name,
        "allowed_resource_oauth2_return_urls": _return_urls(args),
        "custom_jwt": {
            "discovery_url": _discovery_url(args),
            "allowed_audience": _audiences(args),
            "allowed_clients": _clients(args),
            "allowed_scopes": _scopes(args),
            "custom_claims": [],
        },
    }


def _authorizer_configuration(custom_jwt: dict[str, Any]) -> AuthorizerConfiguration:
    return AuthorizerConfiguration(
        custom_jwt=CustomJWTAuthorizerConfiguration(
            discovery_url=custom_jwt["discovery_url"],
            allowed_audience=custom_jwt["allowed_audience"],
            allowed_clients=custom_jwt["allowed_clients"] or None,
            allowed_scopes=custom_jwt["allowed_scopes"] or None,
            custom_claims=custom_jwt["custom_claims"] or None,
        )
    )


def _is_not_found(exc: ClientRequestException) -> bool:
    return (
        getattr(exc, "status_code", None) == 404
        or getattr(exc, "error_code", None) == "AgentIdentityDirectoryService.1002"
    )


def _get_identity(
    client: AgentIdentityClient,
    workload_identity_name: str,
) -> dict[str, Any] | None:
    try:
        response = client.get_workload_identity(
            GetWorkloadIdentityRequest(workload_identity_name=workload_identity_name)
        )
    except ClientRequestException as exc:
        if _is_not_found(exc):
            return None
        raise
    return as_dict(response).get("workload_identity") or {}


def _get_authorizer_configuration(
    client: AgentIdentityClient,
    workload_identity_name: str,
) -> dict[str, Any]:
    response = client.get_workload_identity_authorizer_configuration(
        GetWorkloadIdentityAuthorizerConfigurationRequest(
            workload_identity_name=workload_identity_name
        )
    )
    data = as_dict(response)
    return data.get("workload_identity_authorizer_configuration") or {}


def _list_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return dedupe([item for item in value if isinstance(item, str)])


def _same_strings(current: Any, desired: list[str]) -> bool:
    return sorted(_list_values(current)) == sorted(dedupe(desired))


def _custom_jwt_from_authorizer(authorizer: dict[str, Any]) -> dict[str, Any]:
    config = authorizer.get("authorizer_configuration") or {}
    if not isinstance(config, dict):
        return {}
    custom_jwt = config.get("custom_jwt") or {}
    return custom_jwt if isinstance(custom_jwt, dict) else {}


def _diffs(
    identity: dict[str, Any],
    custom_jwt: dict[str, Any],
    desired: dict[str, Any],
) -> list[str]:
    changes = []
    if not _same_strings(
        identity.get("allowed_resource_oauth2_return_urls"),
        desired["allowed_resource_oauth2_return_urls"],
    ):
        changes.append("allowed_resource_oauth2_return_urls")
    desired_jwt = desired["custom_jwt"]
    if custom_jwt.get("discovery_url") != desired_jwt["discovery_url"]:
        changes.append("custom_jwt.discovery_url")
    if not _same_strings(
        custom_jwt.get("allowed_audience"), desired_jwt["allowed_audience"]
    ):
        changes.append("custom_jwt.allowed_audience")
    for field in ("allowed_clients", "allowed_scopes"):
        if desired_jwt[field]:
            if not _same_strings(custom_jwt.get(field), desired_jwt[field]):
                changes.append(f"custom_jwt.{field}")
        elif field in custom_jwt:
            changes.append(f"custom_jwt.{field}")
    if custom_jwt.get("custom_claims") or (
        not desired_jwt["custom_claims"] and "custom_claims" in custom_jwt
    ):
        changes.append("custom_jwt.custom_claims")
    return changes


def _print_desired(desired: dict[str, Any]) -> None:
    print(f"Desired workload identity: {desired['name']}")
    print("Desired authorizer_type: CUSTOM_JWT")
    print(f"Desired discovery_url: {desired['custom_jwt']['discovery_url']}")
    print("Desired allowed_audience:")
    for audience in desired["custom_jwt"]["allowed_audience"]:
        print(f"  - {audience}")
    print("Desired allowed_clients:")
    if desired["custom_jwt"]["allowed_clients"]:
        for client in desired["custom_jwt"]["allowed_clients"]:
            print(f"  - {client}")
    else:
        print("  (omitted; client-id claim check disabled)")
    print("Desired OAuth2 return URLs:")
    for return_url in desired["allowed_resource_oauth2_return_urls"]:
        print(f"  - {return_url}")


def _create_identity(
    client: AgentIdentityClient,
    desired: dict[str, Any],
) -> None:
    client.create_workload_identity(
        CreateWorkloadIdentityRequest(
            body=CreateWorkloadIdentityReqBody(
                name=desired["name"],
                allowed_resource_oauth2_return_urls=desired[
                    "allowed_resource_oauth2_return_urls"
                ],
                authorizer_type=AuthorizerType.CUSTOM_JWT,
                authorizer_configuration=_authorizer_configuration(
                    desired["custom_jwt"]
                ),
            )
        )
    )


def _update_identity(
    client: AgentIdentityClient,
    desired: dict[str, Any],
) -> None:
    client.update_workload_identity(
        UpdateWorkloadIdentityRequest(
            workload_identity_name=desired["name"],
            body=UpdateWorkloadIdentityReqBody(
                allowed_resource_oauth2_return_urls=desired[
                    "allowed_resource_oauth2_return_urls"
                ],
                authorizer_configuration=_authorizer_configuration(
                    desired["custom_jwt"]
                ),
            ),
        )
    )


def main() -> int:
    args = _parse_args()
    desired = _desired_state(args)
    _print_desired(desired)

    try:
        client = build_client(region=args.region, endpoint=args.endpoint)
        identity = _get_identity(client, args.name)
    except (RuntimeError, SdkException) as exc:
        message = sdk_exception_text(exc) if isinstance(exc, SdkException) else str(exc)
        print(f"Failed to read workload identity: {message}", file=sys.stderr)
        return 1

    if identity is None:
        print("Current state: missing")
        if not args.apply:
            print("Dry-run only. Re-run with --apply to create it.")
            return 0
        try:
            _create_identity(client, desired)
        except SdkException as exc:
            print(
                f"Failed to create workload identity: {sdk_exception_text(exc)}",
                file=sys.stderr,
            )
            return 1
        print("Created local JWT workload identity successfully.")
        return 0

    created_by = identity.get("created_by") or {}
    created_by_type = created_by.get("type") if isinstance(created_by, dict) else ""
    if created_by_type and created_by_type != "CUSTOMER":
        print(
            "Refusing to manage workload identity because it is not "
            f"customer-owned: created_by={created_by}",
            file=sys.stderr,
        )
        return 1

    authorizer_type = identity.get("authorizer_type")
    if authorizer_type != "CUSTOM_JWT":
        print(
            "Refusing to update existing workload identity because "
            f"authorizer_type={authorizer_type!r}; expected CUSTOM_JWT.",
            file=sys.stderr,
        )
        return 1

    try:
        authorizer = _get_authorizer_configuration(client, args.name)
    except SdkException as exc:
        print(
            "Failed to read workload identity authorizer configuration: "
            f"{sdk_exception_text(exc)}",
            file=sys.stderr,
        )
        return 1

    custom_jwt = _custom_jwt_from_authorizer(authorizer)
    changes = _diffs(identity, custom_jwt, desired)
    print("Current state: exists")
    if not changes:
        print("No update needed; local JWT workload identity matches desired state.")
        return 0

    print("Fields that differ:")
    for change in changes:
        print(f"  - {change}")

    if not args.apply:
        print("Dry-run only. Re-run with --apply to update it.")
        return 0

    try:
        _update_identity(client, desired)
    except SdkException as exc:
        print(
            f"Failed to update workload identity: {sdk_exception_text(exc)}",
            file=sys.stderr,
        )
        return 1

    print("Updated local JWT workload identity successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
