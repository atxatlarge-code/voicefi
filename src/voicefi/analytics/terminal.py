"""
Terminal Visualization Studio for VoiceFi Analytics (`vifi stats`).
Renders clean Unicode bar charts, metric scorecards, tool distributions, and developer productivity summaries.
"""

import sys
from typing import Any, Dict, List, Optional

from voicefi.analytics.queries import (
    get_analytics_summary,
    get_daily_turn_volume,
    get_tool_usage_breakdown,
    get_agent_distribution,
    get_cognitive_flow_breakdown,
)



# Terminal ANSI Color Codes
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def render_horizontal_bar(val: int, max_val: int, width: int = 24) -> str:
    """Render a scaled Unicode bar glyph (e.g. ████████░░░░)."""
    if max_val <= 0 or val <= 0:
        return "░" * width
    filled = min(width, max(1, int(round((val / float(max_val)) * width))))
    empty = width - filled
    return f"{CYAN}{'█' * filled}{DIM}{'░' * empty}{RESET}"


def format_stats_dashboard(days: int = 7) -> str:
    """Format the complete terminal dashboard string for the specified time window."""
    summary = get_analytics_summary(days=days)
    daily_volume = get_daily_turn_volume(days=days)
    tool_usage = get_tool_usage_breakdown(days=days)
    agent_dist = get_agent_distribution(days=days)

    time_label = f"Last {days} Days" if days > 0 else "All Time"
    if days == 1:
        time_label = "Today"

    lines = []
    lines.append(f"\n{BOLD}🎙️  VoiceFi Developer Activity & Tool Analytics{RESET} {DIM}({time_label}){RESET}")
    lines.append(f"{DIM}{'─' * 74}{RESET}")

    bd = summary.get("time_saved_breakdown") or {}
    total_hrs = summary.get("estimated_hours_saved", 0.0)
    saved_str = f"~{total_hrs} hours total"
    turns_str = f"{summary['total_turns']} turns"
    spoken_mins_str = f"{summary['total_spoken_minutes']} mins total spoken audio"
    top_persona_str = f"{summary['top_persona']}"
    top_agent_str = f"{summary['top_agent']}"
    latency_str = f"P50: {summary['p50_latency_ms']:.1f}ms  ·  P95: {summary['p95_latency_ms']:.1f}ms"
    barge_str = f"{summary['barge_in_count']} interruptions"

    lines.append(f"  {BOLD}• Total Spoken Turns:{RESET}        {GREEN}{turns_str:<18}{RESET} {DIM}({spoken_mins_str}){RESET}")
    lines.append(f"  {BOLD}• Estimated Time Saved:{RESET}      {YELLOW}{saved_str:<18}{RESET}")

    if total_hrs > 0 or summary["total_turns"] > 0:
        speech_str = bd.get("speech_vs_typing_str", "+0 mins")
        chars_count = summary.get("total_chars", 0)
        lines.append(f"    {DIM}↳ Speech vs Typing:{RESET}        {GREEN}{speech_str:<10}{RESET} {DIM}({chars_count} chars @ 180 wpm vs 50 wpm){RESET}")

        baby_str = bd.get("babysitting_str", "+0 mins")
        lines.append(f"    {DIM}↳ Terminal Babysitting:{RESET}    {GREEN}{baby_str:<10}{RESET} {DIM}({summary['total_turns']} turns async idle avoidance){RESET}")

        if summary.get("dispatches_count", 0) > 0:
            disp_str = bd.get("dispatch_str", "+0 mins")
            lines.append(f"    {DIM}↳ Cross-Agent Handoffs:{RESET}    {GREEN}{disp_str:<10}{RESET} {DIM}({summary['dispatches_count']} dispatches Antigravity ↔ Claude){RESET}")

        if summary.get("memos_count", 0) > 0:
            memo_str = bd.get("memo_str", "+0 mins")
            lines.append(f"    {DIM}↳ Voice Memo Synthesis:{RESET}    {GREEN}{memo_str:<10}{RESET} {DIM}({summary['memos_count']} plans auto-drafted @ 15m){RESET}")

    lines.append(f"  {BOLD}• Primary Voice Persona:{RESET}     {CYAN}{top_persona_str:<18}{RESET}")
    lines.append(f"  {BOLD}• Primary Coding Agent:{RESET}      {MAGENTA}{top_agent_str:<18}{RESET}")
    lines.append(f"  {BOLD}• Acoustic TTS Latency:{RESET}      {BLUE}{latency_str}{RESET}")
    lines.append(f"  {BOLD}• Mid-Speech Barge-Ins:{RESET}      {barge_str}")



    # Daily Turn Volume Bar Chart
    if daily_volume:
        lines.append(f"\n{BOLD}📊 Daily Turn Volume{RESET}")
        lines.append(f"{DIM}{'─' * 74}{RESET}")
        max_daily = max(d["turns"] for d in daily_volume) if daily_volume else 1
        for d in daily_volume:
            bar = render_horizontal_bar(d["turns"], max_daily, width=28)
            lines.append(f"  {DIM}{d['date']}{RESET}  {BOLD}{d['day_name']:<3}{RESET}  [{d['turns']:>4} turns]  {bar}")

    # Tool Usage Breakdown
    if tool_usage:
        lines.append(f"\n{BOLD}🛠️  Tool & Action Distribution{RESET}")
        lines.append(f"{DIM}{'─' * 74}{RESET}")
        for t in tool_usage[:6]:
            lines.append(f"  • {BOLD}{t['tool']:<24}{RESET} {t['count']:>5} calls  {DIM}({t['percentage']:>5.1f}%){RESET}")

    # Agent Distribution
    if agent_dist and len(agent_dist) > 1:
        lines.append(f"\n{BOLD}🤖 Coding Agent Breakdown{RESET}")
        lines.append(f"{DIM}{'─' * 74}{RESET}")
        for a in agent_dist:
            lines.append(f"  • {BOLD}{a['agent']:<24}{RESET} {a['count']:>5} turns  {DIM}({a['percentage']:>5.1f}%){RESET}")

    # Cognitive Flow & Context Switching Dynamics
    flow_data = get_cognitive_flow_breakdown(days=days)
    if flow_data and flow_data.get("total_turns", 0) > 0:
        lines.append(f"\n{BOLD}🧠 Cognitive Flow & Context Switching Dynamics{RESET}")
        lines.append(f"{DIM}{'─' * 74}{RESET}")
        score = flow_data.get("flow_preservation_score", 100.0)
        score_color = GREEN if score >= 85.0 else (YELLOW if score >= 60.0 else MAGENTA)
        mins_saved = flow_data.get("net_flow_minutes_saved", 0.0)

        lines.append(f"  {BOLD}• Flow Preservation Index:{RESET}  {score_color}{score:.1f}% (Deep Flow){RESET}  ·  {GREEN}+{mins_saved:.1f}m net focus saved{RESET}")
        lines.append(f"\n  {DIM}{'Modality':<28} {'Turns':<10} {'Avg Turnaround (CTL)':<22} {'Context Swaps':<14}{RESET}")
        lines.append(f"  {DIM}{'─' * 72}{RESET}")
        for m in flow_data.get("modalities", []):
            name_str = f"{m['icon']} {m['name']}"
            t_str = f"{m['turns']} turns"
            ctl_str = f"{m['avg_ctl']}"
            swaps_str = f"{m['swaps']}"
            lines.append(f"  {BOLD}{name_str:<28}{RESET} {t_str:<10} {CYAN}{ctl_str:<22}{RESET} {DIM}{swaps_str:<14}{RESET}")

    lines.append(f"{DIM}{'─' * 74}{RESET}")
    lines.append(f"{DIM}💡 Tip: Run 'vifi stats --export json' to export your local data, or 'vifi stats --clean' to purge.{RESET}\n")


    return "\n".join(lines)


def print_stats_dashboard(days: int = 7):
    """Print the formatted stats dashboard directly to stdout."""
    print(format_stats_dashboard(days=days))
