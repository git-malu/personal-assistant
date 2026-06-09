"""One-time script: create huaweicloud-sts-provider STS Credential Provider.

Usage: uv run python scripts/create_sts_provider.py
Requires env var: HUAWEICLOUD_AGENCY_URN
  (format: urn:agency:<account-id>:<agency-name>)

Prerequisite: Create IAM Agency in Huawei Cloud console (see plan §1.4)
"""

import os

from agentarts.sdk import IdentityClient

client = IdentityClient(region="cn-southwest-2")

client.create_sts_credential_provider(
    name="huaweicloud-sts-provider",
    agency_urn=os.environ["HUAWEICLOUD_AGENCY_URN"],
    tags=[
        {"key": "env", "value": "dev"},
        {"key": "service", "value": "personal-assistant"},
    ],
)

print("✅ huaweicloud-sts-provider created successfully")
