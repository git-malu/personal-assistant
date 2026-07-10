"""Smoke-test JWT-mode workload access token creation."""

from __future__ import annotations

import argparse
import os
import sys

from huaweicloudsdkagentidentity.v1 import (
    CreateWorkloadAccessTokenForJwtRequest,
    CreateWorkloadAccessTokenForJwtRequestBody,
)
from huaweicloudsdkcore.exceptions.exceptions import SdkException

from agent_identity_common import (
    DEFAULT_REGION,
    as_dict,
    build_client,
    sdk_exception_text,
)

DEFAULT_LOCAL_JWT_WORKLOAD_NAME = "pa-local-jwt-workload"
DEFAULT_USER_TOKEN_ENV = "AGENT_IDENTITY_USER_TOKEN"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Call create_workload_access_token_for_jwt for a workload identity. "
            "The inbound user token is read from an environment variable so it "
            "does not have to appear in shell history."
        )
    )
    parser.add_argument(
        "--workload-identity",
        default=os.getenv(
            "AGENT_IDENTITY_LOCAL_JWT_WORKLOAD_NAME",
            DEFAULT_LOCAL_JWT_WORKLOAD_NAME,
        ),
        help=(
            "Workload identity name. Defaults to "
            f"{DEFAULT_LOCAL_JWT_WORKLOAD_NAME} or "
            "AGENT_IDENTITY_LOCAL_JWT_WORKLOAD_NAME."
        ),
    )
    parser.add_argument(
        "--user-token-env",
        default=DEFAULT_USER_TOKEN_ENV,
        help=(
            "Environment variable containing the inbound user JWT. Defaults "
            f"to {DEFAULT_USER_TOKEN_ENV}."
        ),
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
        "--print-token",
        action="store_true",
        help="Print the WAT. Avoid this in shared terminals and logs.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    user_token = os.getenv(args.user_token_env)
    if not user_token or not user_token.strip():
        print(
            f"Missing inbound user token. Set {args.user_token_env}.",
            file=sys.stderr,
        )
        return 1

    try:
        client = build_client(region=args.region, endpoint=args.endpoint)
        response = client.create_workload_access_token_for_jwt(
            CreateWorkloadAccessTokenForJwtRequest(
                body=CreateWorkloadAccessTokenForJwtRequestBody(
                    workload_name=args.workload_identity,
                    user_token=user_token.strip(),
                )
            )
        )
    except (RuntimeError, SdkException) as exc:
        message = sdk_exception_text(exc) if isinstance(exc, SdkException) else str(exc)
        print(f"Failed to create JWT-mode WAT: {message}", file=sys.stderr)
        return 1

    data = as_dict(response)
    workload_access_token = data.get("workload_access_token") or ""
    print(f"Workload identity: {args.workload_identity}")
    print("JWT-mode WAT exchange: success")
    print(f"Expiration: {data.get('expiration', '')}")
    print(f"Token length: {len(workload_access_token)}")
    if args.print_token:
        print(workload_access_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
