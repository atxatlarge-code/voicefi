#!/usr/bin/env python3
"""
Automatically creates the VoiceFi Product Analytics Dashboard and all insight tiles in PostHog.
Usage:
    export POSTHOG_PERSONAL_KEY="phx_..."
    python3 scripts/create_posthog_dashboard.py
"""

import json
import os
import ssl
import sys
import urllib.request

try:
    import certifi

    ssl_context = ssl.create_default_context(cafile=certifi.where())
except Exception:
    ssl_context = ssl._create_unverified_context()

PROJECT_ID = "574817"
POSTHOG_HOST = "https://us.posthog.com"


def main():
    api_key = os.getenv("POSTHOG_PERSONAL_KEY") or os.getenv("POSTHOG_API_KEY")
    if not api_key:
        print("❌ Error: POSTHOG_PERSONAL_KEY environment variable is not set.")
        print("💡 Create a personal key at: https://us.posthog.com/me/settings/user-api-keys")
        print(
            "   Then run: export POSTHOG_PERSONAL_KEY='phx_...' && python3 scripts/create_posthog_dashboard.py"
        )
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "VoiceFi-Setup/1.0",
    }

    # 1. Create Dashboard
    print(f"🚀 Creating 'VoiceFi Product & Voice Analytics' Dashboard in Project {PROJECT_ID}...")
    dashboard_payload = {
        "name": "VoiceFi Product & Voice Analytics",
        "description": "Real-time analytics for voice interactions, CLI command volume, acoustic latency, and installer conversion.",
        "pinned": True,
        "tags": ["voicefi", "core", "voice"],
    }
    req = urllib.request.Request(
        f"{POSTHOG_HOST}/api/projects/{PROJECT_ID}/dashboards/",
        data=json.dumps(dashboard_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=ssl_context) as resp:
            dashboard = json.loads(resp.read().decode("utf-8"))
            dashboard_id = dashboard["id"]
            print(f"✅ Dashboard created: ID {dashboard_id}")
    except Exception as e:
        print(f"❌ Failed to create dashboard: {e}")
        sys.exit(1)

    # 2. Insights Definitions
    insights = [
        {
            "name": "Daily Active Users & Utterance Volume",
            "query": {
                "kind": "HogQLQuery",
                "query": """
SELECT 
    toDate(timestamp) AS day,
    count(DISTINCT distinct_id) AS active_users,
    countIf(event = 'voice_interaction') AS voice_turns,
    countIf(event = 'cli_command') AS cli_calls
FROM events
WHERE event IN ('voice_interaction', 'cli_command')
GROUP BY day
ORDER BY day DESC
                """.strip(),
            },
        },
        {
            "name": "Voice Interactions by Trigger & Agent",
            "query": {
                "kind": "TrendsQuery",
                "series": [
                    {
                        "kind": "EventsNode",
                        "event": "voice_interaction",
                        "name": "Voice Turns",
                    }
                ],
                "breakdownFilter": {
                    "breakdown": "trigger",
                    "breakdown_type": "event",
                },
            },
        },
        {
            "name": "Acoustic TTS Latency by Voice (P50 & P95)",
            "query": {
                "kind": "HogQLQuery",
                "query": """
SELECT 
    properties.voice AS voice_name,
    count() AS utterances,
    quantile(0.5)(properties.duration_ms) AS p50_latency_ms,
    quantile(0.95)(properties.duration_ms) AS p95_latency_ms
FROM events
WHERE event = 'voice_interaction' AND isNotNull(properties.voice)
GROUP BY voice_name
ORDER BY utterances DESC
                """.strip(),
            },
        },
        {
            "name": "Installation to First Spoken Turn Funnel",
            "query": {
                "kind": "FunnelsQuery",
                "series": [
                    {
                        "kind": "EventsNode",
                        "event": "install_started",
                        "name": "1. Install Started",
                    },
                    {
                        "kind": "EventsNode",
                        "event": "install_completed",
                        "name": "2. Install Completed",
                    },
                    {
                        "kind": "EventsNode",
                        "event": "onboarding_started",
                        "name": "3. Onboarding / First CLI",
                    },
                    {
                        "kind": "EventsNode",
                        "event": "voice_interaction",
                        "name": "4. First Voice Turn",
                    },
                ],
            },
        },
        {
            "name": "Crash & Error Monitor (Zero-PII Traceback Hash)",
            "query": {
                "kind": "HogQLQuery",
                "query": """
SELECT 
    properties.command AS command,
    properties.error_type AS error_type,
    properties.traceback_hash AS tb_hash,
    count() AS crash_count,
    any(properties.error_message) AS sample_msg
FROM events
WHERE event = 'app_crash'
GROUP BY command, error_type, tb_hash
ORDER BY crash_count DESC
                """.strip(),
            },
        },
    ]

    # 3. Create Each Insight Tile & Attach to Dashboard
    for item in insights:
        print(f"📊 Adding insight tile: {item['name']}...")
        payload = {
            "name": item["name"],
            "dashboards": [dashboard_id],
            "query": item["query"],
        }
        tile_req = urllib.request.Request(
            f"{POSTHOG_HOST}/api/projects/{PROJECT_ID}/insights/",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(tile_req, context=ssl_context) as resp:
                print(f"  ✓ Tile '{item['name']}' added successfully.")
        except Exception as ex:
            print(f"  ⚠️ Could not add tile '{item['name']}': {ex}")

    print(
        f"\n🎉 Dashboard complete! View it live at: {POSTHOG_HOST}/project/{PROJECT_ID}/dashboard/{dashboard_id}"
    )


if __name__ == "__main__":
    main()
