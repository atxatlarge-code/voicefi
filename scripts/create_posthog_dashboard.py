#!/usr/bin/env python3
"""
VoiceFi — Automated PostHog Dashboard Creator
Uses the modern PostHog InsightVizNode / HogQL query format to build:
1. Activation Funnel (download -> bootstrap -> complete -> first_spoken_turn)
2. Day 2+ Retention Cohort (first_spoken_turn -> daily_active_ping)
3. Cross-Agent Bridge (Send vs Speak tool distribution)
4. Daily Spoken Turns & Barge-In Interruptions
5. WebMCP & Browser Agent Invocations
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error

POSTHOG_HOST = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")


def main():
    parser = argparse.ArgumentParser(description="Generate VoiceFi PostHog Dashboard")
    parser.add_argument(
        "--key",
        default=os.getenv("POSTHOG_PERSONAL_API_KEY", ""),
        help="PostHog Personal API Key (starts with phx_)",
    )
    parser.add_argument(
        "--project-id",
        default=os.getenv("POSTHOG_PROJECT_ID", "350469"),
        help="PostHog Project / Team ID",
    )
    parser.add_argument(
        "--dashboard-id", default="2066598", help="Existing Dashboard ID to attach to"
    )
    args = parser.parse_args()

    api_key = args.key.strip()
    if not api_key:
        print("\n❌ Error: PostHog Personal API Key missing.")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    project_id = args.project_id.strip()
    dash_id = args.dashboard_id.strip()

    # If no dash_id, create new dashboard
    if not dash_id:
        print("\n📊 Creating new PostHog Dashboard...")
        dash_payload = {
            "name": "🎙️ VoiceFi — Executive, Activation & Cross-Agent Telemetry",
            "description": "Live developer activity, installer drop-off funnel, Day 2+ retention cohorts, and Cross-Agent Bridge metrics.",
            "pinned": True,
        }
        req = urllib.request.Request(
            f"{POSTHOG_HOST}/api/projects/{project_id}/dashboards/",
            data=json.dumps(dash_payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            dash_data = json.loads(resp.read().decode())
            dash_id = str(dash_data["id"])
            print(f"✅ Created Dashboard ID: {dash_id}")
    else:
        print(f"\n📊 Using Dashboard ID: {dash_id}")

    # Insight Definitions using modern InsightVizNode query format
    insights = [
        {
            "name": "🚀 VoiceFi End-to-End Activation Funnel",
            "description": "Installer download -> python bootstrap -> completion -> first spoken turn",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "FunnelsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "name": "1. vifi.sh Downloaded",
                            "event": "install_script_downloaded",
                        },
                        {
                            "kind": "EventsNode",
                            "name": "2. Installer Started",
                            "event": "install_started",
                        },
                        {
                            "kind": "EventsNode",
                            "name": "3. Python Bootstrapped",
                            "event": "python_bootstrapped",
                        },
                        {
                            "kind": "EventsNode",
                            "name": "4. Install Completed",
                            "event": "install_completed",
                        },
                        {
                            "kind": "EventsNode",
                            "name": "5. First Spoken Turn ⭐",
                            "event": "first_spoken_turn",
                        },
                    ],
                    "dateRange": {"date_from": "-30d"},
                    "funnelsFilter": {
                        "layout": "vertical",
                        "funnelVizType": "steps",
                        "funnelOrderType": "ordered",
                        "funnelWindowInterval": 14,
                        "funnelWindowIntervalUnit": "day",
                    },
                },
            },
        },
        {
            "name": "⚡ Cross-Agent Bridge (Send vs Speak)",
            "description": "Distribution of cross-agent task delegations vs direct speech",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "math": "total",
                            "name": "MCP Tool Invocations",
                            "event": "$mcp_tool_call",
                        }
                    ],
                    "dateRange": {"date_from": "-30d"},
                    "breakdownFilter": {"breakdown": "tool_name", "breakdown_type": "event"},
                    "trendsFilter": {"display": "ActionsBarValue"},
                },
            },
        },
        {
            "name": "🔄 Developer Retention Cohort (Day 1 - Day 14)",
            "description": "Developers returning for subsequent active days after first spoken turn",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "RetentionQuery",
                    "dateRange": {"date_from": "-30d"},
                    "retentionFilter": {
                        "period": "Day",
                        "totalIntervals": 14,
                        "retentionType": "retention_first_time",
                        "targetEntity": {"id": "first_spoken_turn", "type": "events"},
                        "returningEntity": {"id": "daily_active_ping", "type": "events"},
                    },
                },
            },
        },
        {
            "name": "🗣️ Daily Spoken Turns & Barge-In Interruptions",
            "description": "Daily spoken volume alongside user acoustic speech interruptions",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "math": "total",
                            "name": "Spoken Turns Completed",
                            "event": "voice_turn_completed",
                        },
                        {
                            "kind": "EventsNode",
                            "math": "total",
                            "name": "Barge-In Interruptions",
                            "event": "barge_in_triggered",
                        },
                    ],
                    "dateRange": {"date_from": "-30d"},
                    "trendsFilter": {"display": "ActionsLineGraph"},
                },
            },
        },
        {
            "name": "🌐 WebMCP & In-Browser Agent Invocations",
            "description": "Activity on WebMCP protocol and in-browser tool auditions",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "math": "total",
                            "name": "WebMCP Pageviews",
                            "event": "$pageview",
                            "properties": [
                                {
                                    "key": "$current_url",
                                    "value": "webmcp",
                                    "operator": "icontains",
                                    "type": "event",
                                }
                            ],
                        },
                        {
                            "kind": "EventsNode",
                            "math": "total",
                            "name": "Browser Voice Auditions",
                            "event": "voicefi_audition_played",
                        },
                    ],
                    "dateRange": {"date_from": "-30d"},
                    "trendsFilter": {"display": "ActionsLineGraph"},
                },
            },
        },
    ]

    print(f"\n📈 Creating and pinning {len(insights)} insights to dashboard {dash_id}...")
    for ins in insights:
        payload = {
            "dashboard": int(dash_id),
            "name": ins["name"],
            "description": ins["description"],
            "query": ins["query"],
        }
        req = urllib.request.Request(
            f"{POSTHOG_HOST}/api/projects/{project_id}/insights/",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                created = json.loads(resp.read().decode())
                print(f"  ✅ Added: '{ins['name']}' (ID: {created.get('id')})")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()
            print(f"  ❌ Error on '{ins['name']}' ({e.code}): {err_body}")

    # Web UI URL uses us.posthog.com (without the 'i.' ingestion subdomain)
    web_host = POSTHOG_HOST.replace("us.i.posthog.com", "us.posthog.com")
    dashboard_url = f"{web_host}/project/{project_id}/dashboard/{dash_id}"
    print("\n🎉 ALL SET! Your private PostHog Dashboard is live at:")
    print(f"👉 {dashboard_url}\n")


if __name__ == "__main__":
    main()
