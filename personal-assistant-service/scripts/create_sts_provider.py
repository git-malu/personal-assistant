"""Create the AgentArts STS Credential Provider for OBS outbound tools.

Required environment:
    HUAWEICLOUD_SDK_AK / HUAWEICLOUD_SDK_SK
    AGENTARTS_STS_AGENCY_URN

Optional environment:
    AGENTARTS_REGION=cn-southwest-2
    AGENTARTS_STS_PROVIDER_NAME=huaweicloud-sts-provider
"""

import os
import sys

from agentarts.sdk import IdentityClient
from huaweicloudsdkcore.exceptions.exceptions import ServiceResponseException

DEFAULT_REGION = "cn-southwest-2"
DEFAULT_PROVIDER_NAME = "huaweicloud-sts-provider"


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def main() -> int:
    region = os.environ.get("AGENTARTS_REGION", DEFAULT_REGION)
    provider_name = os.environ.get(
        "AGENTARTS_STS_PROVIDER_NAME",
        DEFAULT_PROVIDER_NAME,
    )
    agency_urn = _required_env("AGENTARTS_STS_AGENCY_URN")

    client = IdentityClient(region=region)
    try:
        provider = client.create_sts_credential_provider(
            name=provider_name,
            agency_urn=agency_urn,
        )
    except ServiceResponseException as exc:
        if exc.status_code == 409:
            print(f"STS Credential Provider already exists: {provider_name}")
            return 0
        raise

    print(
        "Created STS Credential Provider: "
        f"{getattr(provider, 'name', provider_name)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
