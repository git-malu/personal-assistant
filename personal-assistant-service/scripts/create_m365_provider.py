"""One-time script: create m365-provider OAuth2 Credential Provider.

Usage: uv run python scripts/create_m365_provider.py
Requires env vars: AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID
"""

import os

from agentarts.sdk import IdentityClient
from agentarts.sdk.identity import OAuth2Vendor

client = IdentityClient(region="cn-southwest-2")

client.create_oauth2_credential_provider(
    name="m365-provider",
    vendor=OAuth2Vendor.MICROSOFTOAUTH2,
    client_id=os.environ["AZURE_CLIENT_ID"],
    client_secret=os.environ["AZURE_CLIENT_SECRET"],
    tenant_id=os.environ["AZURE_TENANT_ID"],
)

print("✅ m365-provider created successfully")
