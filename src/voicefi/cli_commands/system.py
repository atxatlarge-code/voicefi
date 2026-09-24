"""
System status, telemetry, licensing, self-learning, dev mode, wake-word, updater, and feedback CLI subcommands.
"""

import os
import sys
import re
import time
from pathlib import Path
from typing import Any

from voicefi import __version__
from voicefi.config import load_config, save_config
from voicefi.license import FeatureGate
from voicefi.feedback import submit_feedback, list_feedback, collect_system_diagnostics


def cmd_dev(args):
    """Launch VoiceFi in foreground development mode with live console logs and auto-takeover."""
    from voicefi.server import stop_all_voicefi_servers, clean_caches, get_launchagent_status
    from voicefi.ui.tray import run_tray

    print("\n🛠️  Preparing VoiceFi DEV Environment...")
    la_status = get_launchagent_status()
    if la_status.get("is_loaded") or la_status.get("pid"):
        print(
            "⏸️  Temporarily stopping background LaunchAgent server to prevent port/lock conflicts..."
        )
        stop_all_voicefi_servers(disable_launchagent=True, timeout_seconds=2.0)
    else:
        # Stop any orphaned processes
        stop_all_voicefi_servers(disable_launchagent=False, timeout_seconds=1.0)

    # Clean stale bytecode and temporary locks
    clean_caches(clean_pycache=True, clean_tmp_state=True, clean_update_cache=True)
    print("🧹 Stale caches and locks cleared.")
    print("🚀 Launching VoiceFi in DEV mode (live logs active, Ctrl+C to exit)...\n")
    try:
        run_tray(force=True)
    except KeyboardInterrupt:
        print("\n👋 VoiceFi DEV mode stopped cleanly.")


def cmd_wake(args):
    """Run interactive foreground 'Hey Viv' wake-word listener with live console logs."""
    from voicefi.config import load_config
    from voicefi.audio.wakeword import WakeWordListener
    from voicefi.audio.recorder import AudioRecorder
    from voicefi.audio.chimes import play_chime
    from voicefi.stt import get_stt_engine
    from voicefi.integrations.injector import send_message_to_antigravity, send_message_to_agent
    from voicefi.stt.biasing import PhoneticNormalizer

    config = load_config(getattr(args, "config", None))
    aliases = list(getattr(config.wakeword, "aliases", ["hey viv", "viv", "hey vifi"]))
    phrase = getattr(config.wakeword, "phrase", "Hey Viv")

    print("\n🎙️  VoiceFi 'Hey Viv' Wake-Word Studio")
    print("==================================================================")
    print(f"  • Primary Trigger:   '{phrase}'")
    print(f"  • Active Aliases:    {', '.join(aliases)}")
    print("  • Target Channel:    Antigravity (agentapi IPC)")
    print(f"  • Acoustic Chime:    {'Enabled' if config.wakeword.chime else 'Disabled'}")
    print("==================================================================")
    print("👉 Say 'Hey Viv' or 'Hey Viv, <your command>' aloud (Ctrl+C to exit)...\n")

    def _on_wake(matched_phrase: str, prompt: str):
        print(f"\n⚡ [WAKE TRIGGERED] Matched '{matched_phrase}'")
        phrase_lower = matched_phrase.lower().strip()
        is_claude = "claude" in phrase_lower or any(
            k in phrase_lower for k in ("claud", "clod", "clawed", "glenn", "hague")
        )
        target_engine = "claude" if is_claude else "antigravity"
        agent_name = "Claude Code" if is_claude else "Antigravity"

        def _dispatch_prompt(raw_text: str):
            norm = PhoneticNormalizer.normalize(raw_text.strip())
            print(f'🚀 Prompt: "{norm}"')

            # Check if on-device intent routing is enabled
            if getattr(getattr(config, "local_model", None), "intent_routing", False):
                from voicefi.local.intent import LocalIntentRouter

                router = LocalIntentRouter(config=config)
                route = router.route_prompt(norm)

                if route.get("status") == "handled_local":
                    spoken = route.get("spoken_response", "")
                    print(f"⚡ [Local Action Handled] {spoken}")
                    from voicefi.tts import get_tts_engine

                    tts = get_tts_engine(config)
                    tts.speak(spoken, block=False)
                    return
                elif route.get("status") == "routed_obsidian":
                    spoken = route.get("spoken_response", "")
                    print(f"💎 [Obsidian Routed] {spoken}")
                    from voicefi.tts import get_tts_engine

                    tts = get_tts_engine(config)
                    tts.speak(spoken, block=False)
                    return
                elif route.get("target") in ("codex", "claude", "antigravity"):
                    routed_engine = route.get("target")
                    active_agent_name = (
                        "ChatGPT / Codex"
                        if routed_engine == "codex"
                        else "Claude Code"
                        if routed_engine == "claude"
                        else "Antigravity"
                    )
                    print(f"📤 Dispatching to {active_agent_name}...")
                    res = send_message_to_agent(
                        text=norm,
                        sender_name=f"{config.user_name} ({matched_phrase})",
                        title=f"Prompt via {matched_phrase}",
                        target_engine=routed_engine,
                        use_headless=True if routed_engine == "claude" else None,
                    )
                    if res.success:
                        print(
                            f"✅ Delivered to {active_agent_name} conversation ({res.delivery_type.upper()})"
                        )
                        if config.audio_cues.enabled:
                            play_chime(config.audio_cues.sent_chime, block=False)
                    else:
                        print(f"⚠️ Dispatch notice: {res.error}")
                    return

            # Default routing
            print(f"📤 Dispatching to {agent_name}...")
            res = send_message_to_agent(
                text=norm,
                sender_name=f"{config.user_name} ({matched_phrase})",
                title=f"Prompt via {matched_phrase}",
                target_engine=target_engine,
                use_headless=True if is_claude else None,
            )
            if res.success:
                print(f"✅ Delivered to {agent_name} conversation ({res.delivery_type.upper()})")
                if config.audio_cues.enabled:
                    play_chime(config.audio_cues.sent_chime, block=False)
            else:
                print(f"⚠️ Dispatch notice: {res.error}")

        if prompt and len(prompt.strip()) >= 3:
            _dispatch_prompt(prompt)
        else:
            print(
                f"🎙️ Wake word detected for {agent_name} without prompt -> Listening for command..."
            )
            if config.audio_cues.enabled:
                play_chime("start", block=False)
            recorder = AudioRecorder(
                sample_rate=config.vad.sample_rate,
                energy_threshold=config.vad.energy_threshold,
                silence_duration=config.vad.silence_duration,
            )
            _, temp_wav = recorder.record_speech_auto()
            try:
                stt = get_stt_engine(config)
                text = stt.transcribe(temp_wav)
                if text and text.strip():
                    _dispatch_prompt(text)
            finally:
                if temp_wav:
                    try:
                        temp_wav.unlink(missing_ok=True)
                    except Exception:
                        pass
        print("\n👂 Resumed listening for 'Hey Viv'...")

    listener = WakeWordListener(
        config=config,
        on_wake=_on_wake,
    )
    listener.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n👋 'Hey Viv' wake listener stopped.")
        listener.stop()


def cmd_update(args):
    """Check for and install VoiceFi software upgrades."""
    from voicefi.updater import check_for_updates, perform_update, get_local_version

    current_ver = get_local_version()

    if getattr(args, "check", False):
        print(f"\n🔍 Checking for VoiceFi updates (current: v{current_ver})...")
        is_avail, latest_ver, url = check_for_updates(force=True)
        if is_avail:
            print(f"✨ Update available: v{current_ver} -> v{latest_ver}")
            print("👉 Run 'vifi update' to upgrade now.")
            if url:
                print(f"🔗 Release: {url}\n")
        else:
            print(f"✅ VoiceFi is up to date (v{current_ver})!\n")
        return

    # Perform update
    print(f"\n🚀 Updating VoiceFi (current: v{current_ver})...")
    custom_repo = getattr(args, "repo", None)
    res = perform_update(repo_url=custom_repo)
    if res.get("success"):
        print(f"\n✅ {res['message']}\n")
    else:
        print(f"\n❌ {res['message']}\n")
        if res.get("error"):
            print(f"Details: {res['error']}\n")


def cmd_feedback(args):
    """Handle feedback, bug reports, and diagnostic submissions."""
    subaction = getattr(args, "feedback_action", "submit")
    if subaction == "list":
        items = list_feedback(limit=getattr(args, "limit", 10))
        if not items:
            print("ℹ️ No feedback submissions recorded yet.")
            return
        print(f"\n📬 Recent Feedback Items ({len(items)}):")
        for it in items:
            print(
                f"  [{it.get('category', 'general').upper()}] {it.get('title')} ({it.get('timestamp', '')[:19]}) - ID: {it.get('id')}"
            )
            if it.get("details"):
                print(f"     Details: {it.get('details')}")
        print()
    else:
        title = " ".join(args.title) if isinstance(args.title, list) else str(args.title)
        details = getattr(args, "details", "") or ""
        category = getattr(args, "category", "general") or "general"
        agent_id = getattr(args, "agent_id", None)
        record = submit_feedback(
            title=title,
            details=details,
            category=category,
            agent_id=agent_id,
            include_diagnostics=not getattr(args, "no_diagnostics", False),
        )
        print(f"✅ Feedback logged successfully (ID: {record['id']}).")
        print("📁 Saved to ~/.voicefi/feedback.jsonl")
        print(
            "⭐ Thank you for helping build VoiceFi! Drop a star on GitHub: https://github.com/atxatlarge-code/voicefi"
        )


def cmd_tier(args):
    """Display active tier, 14-day free trial countdown, and pricing details."""
    config = load_config(getattr(args, "config", None))
    FeatureGate.ensure_trial_started(config)
    FeatureGate.sync_cloud_license(config)
    summary = FeatureGate.get_tier_summary(config)

    print("\n================ VoiceFi Tier & Licensing ================")
    print(f"Status:        {summary['status_text']}")

    if summary["is_licensed"]:
        lic_info = summary.get("license_info", {})
        tag = f" ({lic_info['tag']})" if lic_info.get("tag") else ""
        expires = lic_info.get("expires_at", "Perpetual")
        masked_key = (
            (config.license_key[:12] + "..." + config.license_key[-6:])
            if len(config.license_key) >= 20
            else (config.license_key[:4] + "****")
        )
        print(f"Tier:          {summary['tier']}{tag}")
        print(f"Validity:      {expires}")
        print(f"License Key:   {masked_key}")
        print("Capabilities:  All Pro Features Unlocked")
    elif summary["is_trial"]:
        print(f"Tier:          {summary['tier']}")
        days = summary["trial_days_remaining"]
        hours = summary["trial_hours_remaining"]
        print(f"Free Trial:    🟢 ACTIVE — {days} days remaining ({hours}h total)")
        print(f"Expires At:    {summary['trial_expires_at']}")
        print("Features:      ✓ 20+ Curated Neural & Local Voices")
        print("               ✓ Ultra-Fast Cloud & Groq STT/TTS Relay")
        print("               ✓ Streaming Realtime STT")
        print("               ✓ Mobile & Web Pacing Companion")
        print("               ✓ Multi-Agent Audio Turn Routing")
        print("----------------------------------------------------------")
        print("Upgrade to Pro:")
        print("  • Monthly:         $9 / month (lowest in market, cancel anytime)")
        print(
            "  • Annual Special:  $69 / year (1-Time payment for 1 full year · Save 36% · ~$5.75/mo)"
        )
        print("  • Upgrade URL:     https://voicefi.org#pricing")
        print("  • Activate Key:    vifi license activate <LICENSE_KEY>")
    elif summary["trial_expired"]:
        print(f"Tier:          {summary['tier']}")
        print("Free Trial:    🔴 EXPIRED — Running in Community Mode ($0)")
        print("Features:      ✓ 100% Local Apple Silicon TTS (0ms)")
        print("               ✓ Local Whisper STT & Faster-Whisper")
        print("               ✓ Native Stdio MCP Server & CLI")
        print("----------------------------------------------------------")
        print("Unlock Pro Features ($9/mo or $69/year 1-Time Special):")
        print("  • Upgrade URL:     https://voicefi.org#pricing")
        print("  • Activate Key:    vifi license activate <LICENSE_KEY>")
    else:
        print(f"Tier:          {summary['tier']}")
        print("Community:     $0 / Open-Source Tier")
        print("Upgrade URL:   https://voicefi.org#pricing")

    print("==========================================================\n")


def cmd_license(args):
    """Manage VoiceFi license keys and Pro tier activation."""
    action = getattr(args, "license_action", "status")
    key = getattr(args, "key", None)

    if action in ("help", "where", "find", "recover", "lost"):
        print("\n==========================================================")
        print("🔑 Finding or Recovering Your VoiceFi License Key")
        print("==========================================================")
        print("1. Polar Receipt Email:")
        print("   If you purchased Pro, your cryptographic key was emailed from")
        print("   Polar (notifications@polar.sh) and VoiceFi (talktome@voicefi.org)")
        print("   with the subject 'Your VoiceFi Pro License'.")
        print("\n2. Format of Genuine License Keys:")
        print("   Keys begin with 'VF1-PRO-' followed by expiration and signature:")
        print("   e.g. VF1-PRO-<EXPIRATION>-<ID>.<ED25519_SIGNATURE>")
        print("\n3. 14-Day Free Pro Trial (No Key Required):")
        print("   Testing VoiceFi? You do NOT need a license key or credit card!")
        print("   Run: vifi tier (or start from the AppKit Welcome Window)")
        print("\n4. Lost Key Recovery:")
        print("   Visit your Polar Customer Portal with your checkout email:")
        print("   👉 https://polar.sh/purchases")
        print("   Or contact: support@voicefi.org")
        print("\n5. Activate on This Machine:")
        print("   vifi license activate <YOUR_LICENSE_KEY>")
        print("==========================================================\n")
        return

    if action in ("activate", "set", "apply") or key:
        raw_key = (key or (args.key_args[0] if getattr(args, "key_args", None) else "")).strip()
        if not raw_key:
            print(
                "❌ Error: Please provide a valid license key (e.g. vifi license activate VF1-PRO-<KEY>)"
            )
            return

        config = load_config(getattr(args, "config", None))
        result = FeatureGate.activate_license(raw_key, config=config)
        if not result.get("success"):
            if result.get("is_expired"):
                print(f"\n❌ Error: This license key expired on {result.get('expires_at')}.")
            else:
                print(f"\n❌ Error: {result.get('error', 'Invalid license key signature.')}")
                print("   Please check your license key or visit https://voicefi.org#pricing\n")
            return

        expires_desc = result.get("expires_at", "Perpetual")
        tag_desc = f" ({result['tag']})" if result.get("tag") else ""
        masked_key = (
            (raw_key[:12] + "..." + raw_key[-6:]) if len(raw_key) >= 20 else (raw_key[:4] + "****")
        )

        print("\n🎉 VoiceFi Pro License Successfully Activated!")
        print(f"🔑 License Key: {masked_key}")
        print(
            f"⚡ Tier:        {result.get('tier', 'pro').capitalize()}{tag_desc} · {expires_desc}"
        )
        print("🚀 All Pro features (Streaming STT, 20+ Neural Voices, Cloud Relay) are unlocked!")
        return
    if action in ("generate", "create", "mint", "new"):
        from voicefi.license import generate_license_key

        tier = getattr(args, "tier", "PRO") or "PRO"
        expires = getattr(args, "expires", "PERP") or "PERP"
        tag = getattr(args, "tag", "TESTER") or "TESTER"
        try:
            new_key = generate_license_key(tier=tier, expires=expires, tag=tag)
            print("\n✨ VoiceFi License Key Generated Successfully:")
            print(f"🔑 Key:    {new_key}")
            print(f"⚡ Tier:   {tier.upper()}")
            print(f"⏱️ Exp:    {expires.upper()}")
            print(f"🏷️ Tag:    {tag.upper()}")
            print("\n👉 To activate on any machine:")
            print(f"   vifi license activate {new_key}\n")
            return
        except Exception as e:
            print(f"\n❌ Error generating license key: {e}\n")
            return

    # Default to showing status
    cmd_tier(args)


def cmd_learn(args):
    """Inspect and manage recursive phonetic and brevity self-learning memory."""
    from voicefi.learning.phonetic import PhoneticLearner
    from voicefi.learning.brevity import BrevityLearner
    from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine
    from voicefi.config import load_config
    import time

    phonetic = PhoneticLearner.get_instance()
    brevity = BrevityLearner.get_instance()
    cfg = load_config(getattr(args, "config", None))
    gem = GeminiIntelligenceEngine(cfg)
    subaction = getattr(args, "learn_action", None) or "status"

    if subaction == "teach":
        spoken = getattr(args, "spoken", "")
        canonical = getattr(args, "canonical", "")
        if not spoken or not canonical:
            print('❌ Usage: vifi learn teach "<spoken phrase>" "<canonical command/code>"')
            return
        phonetic.record_correction(spoken, canonical)
        print("\n✅ Learned phonetic mapping:")
        print(f"   Spoken:    '{spoken}'")
        print(f"   Canonical: '{canonical}'")
        print("   Saved to:  ~/.voicefi/phonetic_memory.json\n")
        return

    elif subaction == "scan":
        target_dir = Path(getattr(args, "path", None) or Path.cwd())
        print(f"\n🔍 Scanning workspace for code symbols: {target_dir}...")
        found = phonetic.scan_workspace(target_dir)
        print(f"✅ Indexed {found} project symbols into phonetic self-learning memory.\n")
        return

    elif subaction == "test":
        raw_text = getattr(args, "text", "")
        if not raw_text:
            print('❌ Usage: vifi learn test "<agent output or markdown text>"')
            return
        target_words = brevity.get_optimal_max_words()
        print(f"\n🧪 Distilling Spoken Soundbite (Target: <{target_words} words)...")
        t0 = time.time()
        distilled = gem.distill_spoken_soundbite(
            raw_text, max_words=target_words, fallback_to_heuristics=True
        )
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        provider = gem.get_active_provider()

        print("\n================= Distillation Benchmark =================")
        print(
            f"Provider:        {provider.upper()} ({gem.model if provider == 'gemini' else gem.local_llm_model})"
        )
        print(f"Latency:         {elapsed_ms}ms")
        print(f"Raw Words:       {len(raw_text.split())} words")
        print(f"Distilled Words: {len(distilled.split()) if distilled else 0} words")
        print("---------------------------------------------------------")
        print(f'Output: "{distilled or "No distillation produced"}"')
        print("=========================================================\n")
        return

    elif subaction == "reset":
        phonetic.reset()
        brevity.reset()
        print("\n🗑️  Reset all recursive phonetic and cognitive brevity memory files.\n")
        return

    # Default status view
    p_status = phonetic.get_status()
    b_status = brevity.get_status()
    active_provider = gem.get_active_provider()
    active_stt = getattr(cfg.stt, "provider", "whisper_local")

    print("\n============== VoiceFi Recursive Self-Learning ==============")
    print(
        f"Intelligence Engine: {active_provider.upper()} ({'Gemini Free Tier' if active_provider == 'gemini' else 'Local Ollama' if active_provider == 'ollama' else 'Regex Heuristics (0ms)'})"
    )
    print(
        f"Speech Recognition:  {active_stt.upper()} ({getattr(cfg.stt, 'model_size', 'base.en') if active_stt == 'whisper_local' else 'Cloud'})"
    )
    print(
        f"Phonetic Memory:     {p_status['total_learned_corrections']} learned rules, {p_status['total_project_symbols']} project symbols"
    )
    print(
        f"Spoken Brevity:      {b_status['learned_max_words']} words/turn limit (Interruption rate: {b_status['interruption_rate_pct']}%)"
    )
    print(
        f"Turn Telemetry:      {b_status['total_turns']} total turns ({b_status['total_interruptions']} barge-in interruptions)"
    )
    print("-------------------------------------------------------------")
    if p_status.get("top_corrections"):
        print("Top Learned Phonetic Mappings:")
        for c in p_status["top_corrections"][:5]:
            print(f"  • '{c['spoken']}' -> '{c['canonical']}' ({c['count']} uses)")
    else:
        print("Top Learned Phonetic Mappings: (Built-ins active: pytest, vifi, kubectl, .tsx, .py)")
    print("-------------------------------------------------------------")
    print("Commands:")
    print("  • Scan repository:   vifi learn scan [path]")
    print('  • Test distillation: vifi learn test "<agent text>"')
    print('  • Teach mapping:     vifi learn teach "<spoken>" "<canonical>"')
    print("  • Reset memory:      vifi learn reset")
    print("=============================================================\n")


def cmd_info(args):
    """Display active configuration and system capabilities."""
    from voicefi.server import get_full_server_status

    config = load_config(args.config)
    FeatureGate.ensure_trial_started(config)
    tier_info = FeatureGate.get_tier_summary(config)
    st = get_full_server_status()
    la = st["launchagent"]
    port = st.get("port_5141") or st.get("port_8765") or st.get("port_listener")

    print(f"\n================ VoiceFi v{__version__} ================")
    print("  'Give voice to your agents, and agency for your voice.'")
    print(f"Tier:          {tier_info['status_text']}")
    print(f"TTS Provider:  {config.tts.provider} (Default Voice: {config.tts.voice})")
    print(f"STT Provider:  {config.stt.provider} (Model: {config.stt.model_size})")
    print(f"VAD Silence:   {config.vad.silence_duration}s")
    print(f"Auto-Listen:   {config.antigravity.auto_listen}")
    print(f"Read Aloud:    {config.antigravity.read_summary_aloud}")
    if config.agents:
        print(f"Agents:        {', '.join(config.agents.keys())}")
    if config.subagents:
        print(f"Subagents:     {', '.join(config.subagents.keys())}")
    print("----------------------------------------------------")
    print(
        f"LaunchAgent:   {'🟢 Active' if la['is_loaded'] else '⚪ Inactive'}"
        + (f" (PID {la['pid']})" if la["pid"] else "")
    )
    print(
        "Port 5141:     "
        + (f"🟢 PID {port['pid']} ({port['command_name']})" if port else "⚪ Free")
    )
    print(f"Python Exec:   {st['python_executable']}")
    print(f"Antigravity:   {st['hooks'].get('antigravity') or '❌ Not installed'}")
    print(f"Claude Code:   {st['hooks'].get('claude') or '❌ Not installed'}")
    print("====================================================\n")

    print("Curated Personas: Viv, Christopher, Aria, Sonia, Guy, William, Samantha, Alex")
    print(
        "Run 'vifi ping --all' to test connection & speeds, or 'vifi dev' for live development.\n"
    )


def cmd_stats(args):
    """View local developer activity, tool usage, time saved, and acoustic latency benchmarks."""
    from voicefi.analytics import (
        print_stats_dashboard,
        export_events_json,
        export_events_csv,
        clean_analytics_data,
        reset_analytics_data,
    )

    if getattr(args, "reset", False):
        if getattr(args, "force", False) or input(
            "⚠️ Are you sure you want to wipe all local analytics data? [y/N] "
        ).strip().lower() in ("y", "yes"):
            reset_analytics_data()
            print("✅ Successfully wiped local analytics database (~/.voicefi/analytics.db).")
            return
        else:
            print("Operation cancelled.")
            return

    clean_days = getattr(args, "clean", None)
    if clean_days is not None:
        try:
            days_val = max(0, int(clean_days))
        except (ValueError, TypeError):
            days_val = 30
        pruned = clean_analytics_data(retention_days=days_val)
        if days_val == 0:
            print(
                f"✅ Cleaned local analytics: {pruned} records purged (all-time retention reset)."
            )
        else:
            print(
                f"✅ Cleaned local analytics: {pruned} records older than {days_val} days purged."
            )
        return

    days = 7
    if getattr(args, "today", False):
        days = 1
    elif getattr(args, "all", False):
        days = 0
    elif getattr(args, "days", None) is not None:
        try:
            days = int(args.days)
        except (ValueError, TypeError):
            days = 7

    export_fmt = getattr(args, "export", None)
    try:
        if export_fmt:
            if str(export_fmt).lower() == "csv":
                print(export_events_csv(days=days))
            else:
                print(export_events_json(days=days))
            return

        print_stats_dashboard(days=days)
    except BrokenPipeError:
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                devnull = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull, sys.stdout.fileno())
            except Exception:
                pass
        return
