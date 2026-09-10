"""
Terminal Visualization Studio for VoiceFi Analytics (`vifi stats`).
Renders clean Unicode bar charts, metric scorecards, tool distributions, and developer productivity summaries.
"""

import sys
from typing import Any, Dict, List, Optional

from voicefi.analytics.store import AnalyticsStore
from voicefi.analytics.queries import (
    get_analytics_summary,
    get_daily_turn_volume,
    get_tool_usage_breakdown,
    get_agent_distribution,
    get_cognitive_flow_breakdown,
    _normalize_days,
)

# Terminal ANSI Color Codes
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
RED = "\033[91m"
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


def format_stats_dashboard(days: int = 7, store: Optional[AnalyticsStore] = None) -> str:
    """Format the complete terminal dashboard string for the specified time window."""
    summary = get_analytics_summary(days=days, store=store)
    daily_volume = get_daily_turn_volume(days=days, store=store)
    tool_usage = get_tool_usage_breakdown(days=days, store=store)
    agent_dist = get_agent_distribution(days=days, store=store)

    d, _ = _normalize_days(days, default_days=7)
    time_label = f"Last {d} Days" if d > 0 else "All Time"
    if d == 1:
        time_label = "Today"

    lines = []
    lines.append(
        f"\n{BOLD}🎙️  VoiceFi Developer Activity & Tool Analytics{RESET} {DIM}({time_label}){RESET}"
    )
    lines.append(f"{DIM}{'─' * 74}{RESET}")

    bd = summary.get("time_saved_breakdown") or {}
    total_hrs = summary.get("estimated_hours_saved", 0.0)
    saved_str = f"~{total_hrs} hours total"
    turns_str = f"{summary['total_turns']} turns"
    spoken_mins_str = f"{summary['total_spoken_minutes']} mins total spoken audio"
    top_persona_str = f"{summary['top_persona']}"
    top_agent_str = f"{summary['top_agent']}"
    latency_str = (
        f"P50: {summary['p50_latency_ms']:.1f}ms  ·  P95: {summary['p95_latency_ms']:.1f}ms"
    )
    barge_str = f"{summary['barge_in_count']} interruptions"

    fb = summary.get("feedback_loops") or {}
    total_fb_loops = fb.get("total_loops", 0)
    prompt_returns = fb.get("prompt_returns", 0)
    voice_barge_ins = fb.get("voice_barge_ins", 0)
    one_way_soundbites = fb.get("one_way_soundbites", summary["total_turns"])
    listen_tools = fb.get("listen_tools", 0)
    hook_injections = fb.get("hook_injections", 0)

    lines.append(
        f"  {BOLD}• Agent Soundbites Delivered:{RESET} {GREEN}{turns_str:<18}{RESET} {DIM}(Total Spoken Turns · {spoken_mins_str}){RESET}"
    )
    lines.append(
        f"    {DIM}↳ One-Way Audio Triage:{RESET}   {CYAN}{one_way_soundbites:,} soundbites{RESET} {DIM}(hands-free editor verification){RESET}"
    )
    if total_fb_loops > 0:
        lines.append(
            f"  {BOLD}• ProActive Feedback Loops:{RESET}   {GREEN}{total_fb_loops:,} roundtrips{RESET}  {DIM}(spoken voice returned to agent){RESET}"
        )
        if voice_barge_ins > 0:
            lines.append(
                f"    {DIM}↳ Active Voice Barge-Ins:{RESET} {CYAN}{voice_barge_ins:,} takeovers{RESET}    {DIM}(⚡ acoustic voice VAD interruptions){RESET}"
            )
        if prompt_returns > 0:
            lines.append(
                f"    {DIM}↳ Hands-Free Prompt Returns:{RESET} {CYAN}{prompt_returns:,} deliveries{RESET} {DIM}(🎙️ {listen_tools} listen tools + {hook_injections} hook injections){RESET}"
            )
    lines.append(f"  {BOLD}• Estimated Time Saved:{RESET}      {YELLOW}{saved_str:<18}{RESET}")

    if total_hrs > 0 or summary["total_turns"] > 0:
        baby_str = bd.get("babysitting_str", "+0 mins")
        lines.append(
            f"    {DIM}↳ Zero-Gaze Audio Triage:{RESET} {GREEN}{baby_str:<10}{RESET} {DIM}({summary['total_turns']} turns: 0s idle lag vs ~18s bubble babysitting){RESET}"
        )

        speech_str = bd.get("speech_vs_typing_str", "+0 mins")
        user_chars = bd.get("user_spoken_chars", summary.get("total_chars", 0))
        user_words = int(round(user_chars / 5.0))
        lines.append(
            f"    {DIM}↳ User Speech vs Typing:{RESET}   {GREEN}{speech_str:<10}{RESET} {DIM}({user_chars:,} user dictated chars / ~{user_words:,} words @ ~170 wpm vs 55 wpm typing){RESET}"
        )

        if summary.get("dispatches_count", 0) > 0:
            disp_str = bd.get("dispatch_str", "+0 mins")
            sub_d = bd.get("substantive_dispatches", 0)
            ban_d = bd.get("banter_dispatches", 0)
            detail = (
                f"{summary['dispatches_count']} dispatches: {sub_d} tasks @ 30s + {ban_d} jokes/pings @ 3.5s"
                if (sub_d > 0 or ban_d > 0)
                else f"{summary['dispatches_count']} dispatches Antigravity ↔ Claude"
            )
            lines.append(
                f"    {DIM}↳ Cross-Agent Handoffs:{RESET}    {GREEN}{disp_str:<10}{RESET} {DIM}({detail}){RESET}"
            )

        if summary.get("memos_count", 0) > 0:
            memo_str = bd.get("memo_str", "+0 mins")
            lines.append(
                f"    {DIM}↳ Voice Memo Synthesis:{RESET}    {GREEN}{memo_str:<10}{RESET} {DIM}({summary['memos_count']} specs auto-drafted @ 8 mins){RESET}"
            )

    cons_hrs = bd.get("conservative_hours", 0.0)
    if cons_hrs > 0:
        lines.append(
            f"  {BOLD}• Benchmark Focus Preserved:{RESET} {CYAN}~{cons_hrs} hrs net{RESET} {DIM}(Conservative Turnaround: 44.0s vs 20.8s VoiceFi){RESET}"
        )

    lines.append(f"  {BOLD}• Primary Voice Persona:{RESET}     {CYAN}{top_persona_str:<18}{RESET}")
    lines.append(f"  {BOLD}• Primary Coding Agent:{RESET}      {MAGENTA}{top_agent_str:<18}{RESET}")
    lines.append(f"  {BOLD}• Acoustic TTS Latency:{RESET}      {BLUE}{latency_str}{RESET}")

    comp_t = summary.get("completed_turns", 0)
    int_t = summary.get("interrupted_turns", 0)
    comp_pct = summary.get("completion_rate_pct", 100.0)
    int_pct = summary.get("interruption_rate_pct", 0.0)
    vad_cnt = summary.get("vad_barge_in_count", 0)
    stop_cnt = summary.get("stop_key_count", 0)
    barge_detail = f"{summary['barge_in_count']:,} interruptions"
    if summary["barge_in_count"] > 0:
        barge_detail += f" {DIM}(⚡ {vad_cnt:,} voice VAD · ⎋ {stop_cnt:,} Esc/Stop){RESET}"

    lines.append(
        f"  {BOLD}• Soundbite Playback Ratio:{RESET} {GREEN}{comp_t:,} full{RESET} {DIM}({comp_pct}%){RESET}  ·  {YELLOW}{int_t:,} interrupted{RESET} {DIM}({int_pct}% early stop / barge-in){RESET}"
    )
    lines.append(f"  {BOLD}• Mid-Speech Barge-Ins:{RESET}      {barge_detail}")

    # Daily Turn Volume Bar Chart
    if daily_volume:
        lines.append(f"\n{BOLD}📊 Daily Turn Volume{RESET}")
        lines.append(f"{DIM}{'─' * 74}{RESET}")
        max_daily = max(d["turns"] for d in daily_volume) if daily_volume else 1
        for d in daily_volume:
            bar = render_horizontal_bar(d["turns"], max_daily, width=28)
            lines.append(
                f"  {DIM}{d['date']}{RESET}  {BOLD}{d['day_name']:<3}{RESET}  [{d['turns']:>4} turns]  {bar}"
            )

    # Tool Usage Breakdown
    if tool_usage:
        lines.append(f"\n{BOLD}🛠️  Tool & Action Distribution{RESET}")
        lines.append(f"{DIM}{'─' * 74}{RESET}")
        for t in tool_usage[:6]:
            lines.append(
                f"  • {BOLD}{t['tool']:<24}{RESET} {t['count']:>5} calls  {DIM}({t['percentage']:>5.1f}%){RESET}"
            )

    # Agent Distribution
    if agent_dist and len(agent_dist) > 1:
        lines.append(f"\n{BOLD}🤖 Coding Agent Breakdown{RESET}")
        lines.append(f"{DIM}{'─' * 74}{RESET}")
        for a in agent_dist:
            lines.append(
                f"  • {BOLD}{a['agent']:<24}{RESET} {a['count']:>5} turns  {DIM}({a['percentage']:>5.1f}%){RESET}"
            )

    # Cognitive Flow & Human-AI Interaction (HAI) Dynamics
    flow_data = get_cognitive_flow_breakdown(days=days, store=store)
    if flow_data and flow_data.get("total_turns", 0) > 0:
        lines.append(f"\n{BOLD}🧠 Cognitive Flow & Human-AI Interaction (HAI) Dynamics{RESET}")
        lines.append(f"{DIM}{'─' * 74}{RESET}")
        score = flow_data.get("flow_preservation_score", 100.0)
        score_color = GREEN if score >= 85.0 else (YELLOW if score >= 60.0 else MAGENTA)
        flow_label = (
            "(Deep Flow)"
            if score >= 85.0
            else ("(Moderate Flow)" if score >= 60.0 else "(Fragmented Flow)")
        )
        mins_saved = flow_data.get("net_flow_minutes_saved", 0.0)
        polling_mins = flow_data.get("visual_polling_avoided_mins", 0.0)
        gaze_pct = flow_data.get("gaze_retention_pct", 100.0)

        saved_focus_str = (
            f"+{mins_saved / 60.0:.1f} hrs"
            if mins_saved >= 60.0
            else f"+{mins_saved:.1f} mins"
        )
        polling_str = (
            f"+{polling_mins / 60.0:.1f} hrs"
            if polling_mins >= 60.0
            else f"+{polling_mins:.1f} mins"
        )

        lines.append(
            f"  {BOLD}• Flow Preservation Index:{RESET}  {score_color}{score:.1f}% {flow_label}{RESET}  ·  {GREEN}{saved_focus_str} net focus saved{RESET}"
        )
        lines.append(
            f"  {BOLD}• Zero-Gaze Triage Focus:{RESET}   {CYAN}{polling_str} visual polling avoided{RESET}  ·  {DIM}{gaze_pct:.1f}% eyes-in-editor{RESET}"
        )

        if "zero_swap_actions" in flow_data:
            zsa = flow_data["zero_swap_actions"]
            tot_z = zsa.get("total_actions", 0)
            if tot_z > 0:
                lines.append(
                    f"  {BOLD}• Zero-Swap Actions:{RESET}        {GREEN}{tot_z:,} actions taken with 0 focus switches{RESET}"
                )
                lines.append(
                    f"    {DIM}↳ 🎙️ Spoken Hands-Free Turns:{RESET}   {CYAN}{zsa.get('spoken_turns', 0):<5}{RESET} {DIM}(native IPC mic input & soundbite triage){RESET}"
                )
                lines.append(
                    f"    {DIM}↳ 🤖 Cross-Agent Bridge:{RESET}         {MAGENTA}{zsa.get('delegations', 0):<5}{RESET} {DIM}(daemon dispatches without window hijacking){RESET}"
                )
                lines.append(
                    f"    {DIM}↳ 🔔 Sound Effects & Audio Cues:{RESET} {YELLOW}{zsa.get('sfx_cues', 0):<5}{RESET} {DIM}(chimes, drums & acoustic notifications){RESET}"
                )
                lines.append(
                    f"    {DIM}↳ ⎋ Instant Stop / Esc Controls:{RESET} {RED}{zsa.get('stop_controls', 0):<5}{RESET} {DIM}(instant cancellations without window switching){RESET}"
                )

        keystrokes = bd.get("keystrokes_saved", 0)
        window_swaps = bd.get("window_swaps_saved", 0)
        reading_saved = bd.get("reading_words_saved", 0)
        if keystrokes > 0 or window_swaps > 0:
            lines.append(f"  {BOLD}• Physical & Cognitive Relief:{RESET}")
            if keystrokes > 0:
                lines.append(
                    f"    {DIM}↳ Mechanical Keystrokes:{RESET} {GREEN}{keystrokes:,} keys eliminated{RESET} {DIM}(~{int(round(keystrokes/5.0)):,} words spoken instead of typed){RESET}"
                )
            if window_swaps > 0:
                lines.append(
                    f"    {DIM}↳ Context Swaps Avoided:{RESET}  {CYAN}~{window_swaps:,} Cmd+Tab switches & clicks bypassed{RESET}"
                )
            if reading_saved > 0:
                lines.append(
                    f"    {DIM}↳ Reading Distillation:{RESET}   {YELLOW}~{reading_saved:,} raw markdown words filtered{RESET} {DIM}(~84.8% visual reduction){RESET}"
                )

        lines.append(
            f"\n  {DIM}{'Modality':<30} {'Turns':<10} {'Avg Turnaround (CTL)':<22} {'Context Swaps':<14}{RESET}"
        )
        lines.append(f"{DIM}{'─' * 74}{RESET}")
        for m in flow_data.get("modalities", []):
            name_str = f"{m['icon']} {m['name']}"
            t_str = f"{m['turns']} turns"
            ctl_str = f"{m['avg_ctl']}"
            swaps_str = f"{m['swaps']}"
            lines.append(
                f"  {BOLD}{name_str:<30}{RESET} {t_str:<10} {CYAN}{ctl_str:<22}{RESET} {DIM}{swaps_str:<14}{RESET}"
            )

    lines.append(f"{DIM}{'─' * 74}{RESET}")
    lines.append(
        f"  ⭐ {BOLD}Star on GitHub:{RESET}      {CYAN}https://github.com/atxatlarge-code/voicefi{RESET}"
    )
    lines.append(
        f"  💬 {BOLD}Feedback & Ideas:{RESET}    {DIM}vifi feedback submit \"<your thoughts>\"{RESET}"
    )
    lines.append(f"{DIM}{'─' * 74}{RESET}")
    lines.append(
        f"{DIM}💡 Tip: Run 'vifi stats --export json' to export your local data, or 'vifi stats --clean' to purge.{RESET}\n"
    )

    return "\n".join(lines)


def print_stats_dashboard(days: int = 7, store: Optional[AnalyticsStore] = None):
    """Print the formatted stats dashboard directly to stdout."""
    print(format_stats_dashboard(days=days, store=store))
