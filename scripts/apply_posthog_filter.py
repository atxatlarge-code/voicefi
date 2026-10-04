#!/usr/bin/env python3
"""
Apply global internal IP / machine exclusion filter to PostHog Dashboard.
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

POSTHOG_HOST = os.getenv("POSTHOG_HOST", "https://us.posthog.com")


def main():
    parser = argparse.ArgumentParser(description="Apply internal filter to PostHog Dashboard")
    parser.add_argument(
        "--key",
        default=os.getenv("POSTHOG_PERSONAL_API_KEY", ""),
        help="PostHog Personal API Key (starts with phx_)",
    )
    parser.add_argument(
        "--project-id",
        default=os.getenv("POSTHOG_PROJECT_ID", "350469"),
        help="PostHog Project ID",
    )
    parser.add_argument(
        "--dashboard-id",
        default=os.getenv("POSTHOG_DASHBOARD_ID", "2066598"),
        help="PostHog Dashboard ID",
    )
    parser.add_argument(
        "--exclude-ip",
        default="72.178.121.96",
        help="Internal IP to exclude",
    )
    args = parser.parse_args()

    api_key = args.key.strip()
    if not api_key:
        print("❌ Error: Missing PostHog Personal API Key.")
        print("👉 Generate one at: https://us.posthog.com/settings/user-api-keys")
        print("Then run: python3 scripts/apply_posthog_filter.py --key phx_...")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    url = f"{POSTHOG_HOST}/api/projects/{args.project_id}/dashboards/{args.dashboard_id}/"
    payload = {
        "filters": {
            "properties": [
                {
                    "key": "$ip",
                    "operator": "is_not",
                    "value": [args.exclude_ip],
                    "type": "event",
                }
            ]
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="PATCH",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            print(
                f"✅ Success! Dashboard '{data.get('name')}' updated with filter: $ip != {args.exclude_ip}"
            )
            print(
                f"👉 Live Dashboard: {POSTHOG_HOST}/project/{args.project_id}/dashboard/{args.dashboard_id}"
            )
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error {e.code}: {e.read().decode()}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
