"""
Ambient listening, meeting transcription, and Obsidian knowledge vault CLI subcommands.
"""

import os
import sys
import time
import datetime
from pathlib import Path
from typing import Any

from voicefi.config import load_config, save_config


def cmd_ambient(args):
    """Ambient background listening & proactive meeting co-pilot."""
    action = getattr(args, "ambient_action", "start") or "start"

    from voicefi.integrations.meeting import MeetingNoteTaker, ActionStatus

    note_taker = MeetingNoteTaker.get_instance()

    if action == "start":
        from voicefi.audio.ambient import AmbientAudioStream
        from voicefi.stt import get_stt_engine

        config = load_config(getattr(args, "config", None))
        stt = get_stt_engine(config)

        title = getattr(args, "title", None)
        output_path = getattr(args, "output", None)
        speaker = getattr(args, "speaker", None)
        auto_exec = getattr(args, "auto_execute", True)

        session = note_taker.start_session(
            title=title,
            output_path=output_path,
            auto_execute_actions=auto_exec,
            speaker_name=speaker,
        )

        print("\n🎙️ Starting VoiceFi ProActive Meeting Note Taker...")
        print(f"📋 Title: {session.title}")
        print(f"📄 Notes File: {session.markdown_path}")
        print(f"⚡ Auto-Execute Actions: {'✅ Enabled' if auto_exec else '❌ Disabled'}")
        print("💡 Listening in the background. Press Ctrl+C to finalize & save meeting notes.\n")

        def _on_utterance(audio_data, sample_rate):
            text = stt.transcribe(audio_data, sample_rate=sample_rate)
            if text:
                utt = note_taker.record_utterance(text, speaker_name=speaker)
                action_badge = " ⚡ [Action Triggered]" if utt.is_actionable else ""
                print(f'📝 `[{utt.timestamp_str}]` {utt.speaker}: "{utt.text}"{action_badge}')

                if utt.is_actionable and session.action_items:
                    latest_action = session.action_items[-1]
                    res_str = latest_action.result_summary or latest_action.title
                    print(f"   👉 [{latest_action.category.value}] {res_str}")

        stream = AmbientAudioStream(
            sample_rate=config.vad.sample_rate,
            energy_threshold=config.proactive.meeting_assistant.energy_threshold,
            silence_duration=config.proactive.meeting_assistant.silence_duration,
            max_utterance_duration=config.proactive.meeting_assistant.max_utterance_seconds,
            on_utterance=_on_utterance,
        )
        stream.start()
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            stream.stop()
            final_session = note_taker.stop_session()
            print("\n" + "=" * 60)
            print("🏁 Meeting Session Finalized!")
            print(
                f"📄 Notes saved to: {final_session.markdown_path if final_session else session.markdown_path}"
            )
            if final_session and final_session.action_items:
                print("\n⚡ Actions Executed Along The Way:")
                for a in final_session.action_items:
                    print(
                        f"  • [{a.category.value}] {a.title} -> {a.result_summary or a.status.value}"
                    )
            print("=" * 60 + "\n")

    elif action == "stop":
        session = note_taker.stop_session()
        if session:
            print(f"\n✅ Meeting '{session.title}' finalized.")
            print(f"📄 Notes saved to: {session.markdown_path}")
            print(f"⏱️ Total Duration: {session.duration_formatted}")
            print(f"📝 Spoken Turns: {len(session.utterances)}")
            print(f"⚡ Actions Recorded: {len(session.action_items)}\n")
        else:
            print("\n⚪ No active meeting session found to stop.\n")

    elif action == "status":
        session = note_taker.active_session
        if session and session.status == "active":
            print(f"\n🟢 Active Meeting Session: {session.title}")
            print(f"  • Elapsed Duration: {session.duration_formatted}")
            print(f"  • Spoken Turns: {len(session.utterances)}")
            print(f"  • Decisions Recorded: {len(session.decisions)}")
            print(
                f"  • Actions Executed: {len([a for a in session.action_items if a.status == ActionStatus.COMPLETED])}"
            )
            print(f"  • Notes File: {session.markdown_path}\n")
        else:
            config = load_config(getattr(args, "config", None))
            print("\n⚪ ProActive Meeting Assistant: Standing by")
            print(f"  • Storage Directory: {config.proactive.meeting_assistant.notes_dir}")
            print(
                f"  • Auto-Execute Actions: {'✅ Enabled' if config.proactive.meeting_assistant.auto_execute_actions else '❌ Disabled'}"
            )
            print("  • Start on-demand with: 'vifi meeting start'\n")

    elif action == "list":
        files = note_taker.list_saved_sessions()
        if not files:
            print("\n📂 No saved meeting notes found yet.\n")
        else:
            print(f"\n📂 Saved Meeting Notes ({len(files)} sessions):")
            for f in files[:15]:
                dt = datetime.datetime.fromtimestamp(f["modified_at"]).strftime("%Y-%m-%d %H:%M")
                print(f"  • [{dt}] {f['title']} ({f['filename']})")
            print()

    elif action == "show":
        files = note_taker.list_saved_sessions()
        if not files:
            print("\n📂 No saved meeting notes found.\n")
            return
        target_id = getattr(args, "target", "latest") or "latest"
        target_file = files[0]["filepath"]
        if target_id != "latest":
            matched = [
                f["filepath"]
                for f in files
                if target_id in f["filename"] or target_id in f["title"]
            ]
            if matched:
                target_file = matched[0]

        with open(target_file, "r", encoding="utf-8") as f:
            print("\n" + f.read() + "\n")

    elif action in ("test", "simulate"):
        interactive = getattr(args, "interactive", False)
        import importlib.util
        from pathlib import Path

        qa_path = (
            Path(__file__).resolve().parent.parent.parent / "scripts" / "qa_meeting_simulation.py"
        )
        spec = importlib.util.spec_from_file_location("qa_meeting_simulation", str(qa_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        suite = mod.MeetingQASuite(verbose=True)
        if interactive:
            suite.run_interactive_tester()
        else:
            success = suite.run_automated_simulation()
            if not success:
                import sys

                sys.exit(1)


cmd_meeting = cmd_ambient


def cmd_obsidian(args):
    """Manage and install VoiceFi plugin into Obsidian vaults."""
    from voicefi.integrations.obsidian import (
        is_obsidian_installed,
        install_obsidian_app,
        find_obsidian_vaults,
        install_plugin_to_vault,
        create_starter_vault,
    )

    action = getattr(args, "obsidian_action", None) or "install"

    if action == "list":
        if not is_obsidian_installed():
            print("\n⚠️  Obsidian is not installed on this Mac.")
            print("   Run 'vifi obsidian install' to automatically download and configure it!\n")

        vaults = find_obsidian_vaults()
        if not vaults:
            print("\n🔍 No registered Obsidian vaults found on this machine.")
            print("   Default location: ~/Documents/Obsidian Vault\n")
            return

        print(f"\n📚 Discovered Obsidian Vaults ({len(vaults)} found):")
        for i, v in enumerate(vaults, 1):
            status = "🟢 (Active / Open)" if v["open"] else "⚪"
            print(f"   {i}. {status} {v['name']}")
            print(f"      Path: {v['path']}")
        print()
        return

    elif action == "install":
        target_vault = getattr(args, "vault", None)
        install_all = getattr(args, "all", False)

        print("\n🎙️  VoiceFi Obsidian Plugin Installer")
        print("   'Second Brain, Second Voice • The vocal cords for your vault.'\n")

        # 1. Check if Obsidian app itself is installed
        if not is_obsidian_installed():
            print("⚠️  Obsidian.app is not currently installed on your Mac.")
            install_app = getattr(args, "install_app", False)
            if install_app or input(
                "👉 Would you like VoiceFi to install Obsidian for you now? [Y/n]: "
            ).strip().lower() in ("", "y", "yes"):
                install_obsidian_app()
            else:
                print("💡 You can download Obsidian anytime from https://obsidian.md/download\n")

        # 2. Discover or create vault
        if target_vault:
            targets = [Path(target_vault)]
        else:
            discovered = find_obsidian_vaults()
            if not discovered:
                print(
                    "📁 No existing vaults found. Creating a new starter Obsidian Vault at ~/Documents/Obsidian Vault..."
                )
                starter_path = create_starter_vault()
                targets = [starter_path]
            elif install_all:
                targets = [v["path"] for v in discovered]
            else:
                targets = [discovered[0]["path"]]

        installed_count = 0
        for vault_p in targets:
            try:
                print(f"📦 Installing VoiceFi plugin to: {vault_p.name} ({vault_p})...")
                install_plugin_to_vault(vault_p)
                print(f"   ✅ Plugin bundle copied to: {vault_p}/.obsidian/plugins/voicefi")
                print("   🚀 Enabled in community-plugins.json")
                installed_count += 1
            except Exception as e:
                print(f"   ❌ Error installing to {vault_p}: {e}")

        if installed_count > 0:
            print(f"\n🎉 Successfully installed VoiceFi into {installed_count} vault(s)!")
            print("💡 Next Step: Open Obsidian and press Cmd+R (or restart Obsidian) to activate.")
            print(
                "🎙️ Look for the Microphone icon in your left sidebar and the status bar at the bottom!\n"
            )

    elif action == "status":
        from voicefi.integrations.obsidian import (
            is_obsidian_installed,
            find_obsidian_vaults,
            get_primary_vault,
            get_daily_note_path,
            is_plugin_installed,
        )

        print("\n💎 Obsidian Integration Status:")
        print(f"   App Installed:   {'✅ Yes' if is_obsidian_installed() else '❌ No'}")
        pv = get_primary_vault()
        if pv:
            print(f"   Primary Vault:   {pv.name} ({pv})")
            dn = get_daily_note_path(pv)
            print(
                f"   Today's Note:    {dn.name} ({'✅ Exists' if dn.is_file() else '⚪ Not created yet'})"
            )
            print(
                f"   VoiceFi Plugin:  {'✅ Installed' if is_plugin_installed(pv) else '⚪ Not installed (run vifi obsidian install)'}"
            )
        else:
            print("   Primary Vault:   None found")
        vaults = find_obsidian_vaults()
        print(f"   Total Vaults:    {len(vaults)}\n")
        return

    elif action == "today":
        from voicefi.integrations.obsidian import get_today_note_content

        res = get_today_note_content()
        if res.get("status") == "ok":
            print(f"\n💎 Obsidian Daily Note ({res['file_name']}) in '{res['vault_name']}':")
            print("─" * 60)
            print(res.get("content", ""))
            print("─" * 60 + "\n")
        else:
            print(f"❌ Error reading daily note: {res.get('error')}\n")
        return

    elif action == "capture":
        return cmd_capture(args)

    elif action == "launch":
        engine = getattr(args, "engine", "antigravity") or "antigravity"
        from voicefi.integrations.obsidian import launch_agent_in_vault

        res = launch_agent_in_vault(engine=engine)
        if res.get("status") == "ok":
            print(f"\n🚀 {res.get('message')}\n")
        else:
            print(f"\n❌ Error launching agent: {res.get('error')}\n")
        return


def cmd_capture(args):
    """Direct quick voice capture into Obsidian daily note (100% offline, 0-latency, 0-tokens)."""
    from voicefi.integrations.obsidian import append_quick_capture_to_vault, get_primary_vault
    from pathlib import Path

    raw_text = getattr(args, "text", None)
    if isinstance(raw_text, list):
        text = " ".join(raw_text).strip()
    elif isinstance(raw_text, str):
        text = raw_text.strip()
    else:
        text = ""

    vault_str = getattr(args, "vault", None)
    vp = Path(vault_str) if vault_str else None

    if not text:
        print("\n🎙️  VoiceFi Quick Capture")
        print("   Listening from microphone... Speak your note, pause when finished.")
        try:
            from voicefi.audio.recorder import AudioRecorder
            from voicefi.stt import get_stt_engine

            cfg = load_config()
            recorder = AudioRecorder(cfg)
            print("🔴 Recording... (speak now)")
            audio_data = recorder.record_speech_auto(timeout=15.0)
            if audio_data is not None and len(audio_data) > 0:
                print("⚡ Transcribing locally with Whisper...")
                stt = get_stt_engine(cfg)
                text = stt.transcribe(audio_data).strip()
        except Exception as e:
            print(f"❌ Recording error: {e}")
            return

    if not text:
        print("⚠️  No speech or text captured.\n")
        return

    res = append_quick_capture_to_vault(text, vault_path=vp)
    if res.get("status") == "ok":
        print(
            f"\n✅ Appended to Obsidian ({res['vault_name']}/{res['daily_note_name']}) at {res['time']}:"
        )
        print(f"   {res['entry']}\n")
    else:
        print(f"\n❌ Error appending to vault: {res.get('error')}\n")
