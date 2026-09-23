"""
Voice memo buffer recording, synthesis, and export subcommands.
"""

import time
from pathlib import Path
from typing import Any

from voicefi.config import load_config
from voicefi.stt import get_stt_engine
from voicefi.memo import (
    MemoBufferRecorder,
    MemoSynthesizer,
    MemoStore,
    MemoRecording,
)


def cmd_memo(args):
    """Handle voice memo buffer recording, synthesis, and management."""
    config = load_config(args.config)
    store = MemoStore()
    action = getattr(args, "memo_action", None) or "record"

    if action == "record":
        duration_arg = getattr(args, "duration", None)
        if duration_arg is not None:
            duration_str = str(duration_arg).strip().lower()
            if duration_str.endswith("m"):
                duration = float(duration_str[:-1]) * 60
            elif duration_str.endswith("s"):
                duration = float(duration_str[:-1])
            else:
                duration = float(duration_str)
        else:
            duration = config.memo.default_duration_seconds

        title = getattr(args, "title", None) or "Voice Memo"
        no_synth = getattr(args, "no_synth", False)
        out_path = getattr(args, "out", None)
        clipboard = getattr(args, "clipboard", False) or config.memo.export_to_clipboard

        recorder = MemoBufferRecorder(
            target_duration_seconds=duration,
            sample_rate=config.vad.sample_rate,
            energy_threshold=config.memo.energy_threshold,
            auto_extend_seconds=config.memo.auto_extend_seconds,
        )

        audio_data, temp_wav, actual_duration = recorder.record_memo_session(interactive=True)

        print("\n⏳ Transcribing developer stream of consciousness...")
        stt = get_stt_engine(config)
        raw_transcript = ""
        try:
            raw_transcript = stt.transcribe(temp_wav)
        except Exception as e:
            print(f"❌ Transcription error: {e}")
            return

        if not raw_transcript.strip():
            print("⚠️ No speech detected in recorded audio.")
            return

        word_count = len(raw_transcript.split())
        recording = MemoRecording(
            title=title,
            duration_seconds=actual_duration,
            target_duration_seconds=duration,
            audio_path=str(temp_wav),
            raw_transcript=raw_transcript,
            word_count=word_count,
        )

        synthesis = None
        if not no_synth and config.memo.auto_synthesize:
            print("🧠 Synthesizing Implementation Plan, Mermaid Diagram, and PR Checklist...\n")
            synthesizer = MemoSynthesizer(config)
            synthesis = synthesizer.synthesize(
                raw_speech=raw_transcript,
                memo_id=recording.id,
                custom_title=title if title != "Voice Memo" else None,
            )
            recording.title = synthesis.title

        memo_dir = store.save_memo(recording, synthesis)
        print(f"💾 Saved Voice Memo `{recording.id}` ({recording.title}) to {memo_dir}")

        if synthesis:
            print("\n" + "=" * 70)
            print(synthesis.to_markdown())
            print("=" * 70 + "\n")

            if out_path:
                dest = Path(out_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(synthesis.to_markdown(), encoding="utf-8")
                print(f"📄 Exported plan to {dest}")

            if clipboard:
                try:
                    import subprocess

                    subprocess.run(
                        ["pbcopy"], input=synthesis.to_markdown().encode("utf-8"), check=True
                    )
                    print("📋 Copied synthesized plan to clipboard!")
                except Exception:
                    pass

    elif action in ("synth", "synthesize", "clean"):
        memo_id = getattr(args, "memo_id", None)
        text_arg = getattr(args, "text", None)
        file_arg = getattr(args, "file", None)
        title = getattr(args, "title", None)
        out_path = getattr(args, "out", None)
        clipboard = getattr(args, "clipboard", False) or config.memo.export_to_clipboard

        raw_speech = ""
        recording = None

        if text_arg:
            raw_speech = " ".join(text_arg) if isinstance(text_arg, list) else str(text_arg)
        elif file_arg:
            f_path = Path(file_arg)
            if not f_path.is_file():
                print(f"❌ File not found: {file_arg}")
                return
            raw_speech = f_path.read_text(encoding="utf-8")
        elif memo_id:
            res = store.get_memo(memo_id)
            if not res:
                print(f"❌ Memo `{memo_id}` not found.")
                return
            recording, _ = res
            raw_speech = recording.raw_transcript
            if not title:
                title = recording.title
        else:
            print("❌ Please specify a memo ID, --text '...', or --file <path> to synthesize.")
            return

        if not raw_speech.strip():
            print("❌ No speech text to synthesize.")
            return

        print("🧠 Synthesizing Implementation Plan, Architectural Diagram, and PR Checklist...\n")
        synthesizer = MemoSynthesizer(config)
        mid = recording.id if recording else None
        synthesis = synthesizer.synthesize(raw_speech=raw_speech, memo_id=mid, custom_title=title)

        if recording:
            recording.title = synthesis.title
            store.save_memo(recording, synthesis)
        else:
            recording = MemoRecording(
                id=synthesis.memo_id,
                title=synthesis.title,
                duration_seconds=0.0,
                target_duration_seconds=180.0,
                raw_transcript=raw_speech,
                word_count=len(raw_speech.split()),
            )
            store.save_memo(recording, synthesis)

        print("=" * 70)
        print(synthesis.to_markdown())
        print("=" * 70 + "\n")

        if out_path:
            dest = Path(out_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(synthesis.to_markdown(), encoding="utf-8")
            print(f"📄 Exported plan to {dest}")

        if clipboard:
            try:
                import subprocess

                subprocess.run(
                    ["pbcopy"], input=synthesis.to_markdown().encode("utf-8"), check=True
                )
                print("📋 Copied synthesized plan to clipboard!")
            except Exception:
                pass

    elif action == "list":
        limit = getattr(args, "limit", 20)
        memos = store.list_memos(limit=limit)
        if not memos:
            print("📭 No voice memos recorded yet.")
            print(
                "👉 Run 'vg memo record' or 'vg memo record --duration 3m' to capture a brain dump!"
            )
            return

        print(f"\n{'ID':<10} {'CREATED':<20} {'DURATION':<10} {'WORDS':<8} {'SYNTH':<7} {'TITLE'}")
        print("─" * 78)
        for m in memos:
            created = m.get("created_at", "")[:19].replace("T", " ")
            dur = f"{int(m.get('duration_seconds', 0)) // 60:02d}:{int(m.get('duration_seconds', 0)) % 60:02d}"
            synth_icon = "✅ Yes" if m.get("has_synthesis") else "❌ No"
            words = str(m.get("word_count", 0))
            title = m.get("title", "Voice Memo")[:25]
            mid = m.get("id", "")
            print(f"{mid:<10} {created:<20} {dur:<10} {words:<8} {synth_icon:<7} {title}")
        print("─" * 78 + "\n")

    elif action == "show":
        memo_id = args.memo_id
        res = store.get_memo(memo_id)
        if not res:
            print(f"❌ Memo `{memo_id}` not found.")
            return
        recording, synthesis = res

        if getattr(args, "transcript_only", False):
            print(recording.raw_transcript)
        elif getattr(args, "diagram_only", False) and synthesis:
            if hasattr(synthesis, "architectural_diagram") and synthesis.architectural_diagram:
                print("```mermaid")
                print(synthesis.architectural_diagram.mermaid_code)
                print("```")
            else:
                print("No architectural diagram in this memo.")
        elif getattr(args, "checklist_only", False) and synthesis:
            if hasattr(synthesis, "pr_checklist") and synthesis.pr_checklist:
                for task in synthesis.pr_checklist.core_tasks:
                    print(f"- [ ] {task}")
                for test in synthesis.pr_checklist.testing_and_verification:
                    print(f"- [ ] {test}")
                for edge in synthesis.pr_checklist.edge_cases_and_security:
                    print(f"- [ ] {edge}")
            else:
                print("No PR checklist in this memo.")
        elif synthesis:
            print(synthesis.to_markdown())
        else:
            print(f"# Voice Memo: {recording.title} (`{recording.id}`)")
            print(
                f"Duration: {int(recording.duration_seconds) // 60:02d}:{int(recording.duration_seconds) % 60:02d} | Words: {recording.word_count}"
            )
            print("\n## Raw Transcript")
            print(recording.raw_transcript)
            print(
                "\n💡 Run 'vg memo synth "
                + recording.id
                + "' to generate structured implementation plan."
            )

    elif action == "export":
        memo_id = args.memo_id
        res = store.get_memo(memo_id)
        if not res:
            print(f"❌ Memo `{memo_id}` not found.")
            return
        recording, synthesis = res
        content = synthesis.to_markdown() if synthesis else recording.raw_transcript

        out_path = getattr(args, "out", None)
        if out_path:
            dest = Path(out_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            print(f"📄 Exported memo `{memo_id}` to {dest}")

        if getattr(args, "clipboard", False) or not out_path:
            try:
                import subprocess

                subprocess.run(["pbcopy"], input=content.encode("utf-8"), check=True)
                print(f"📋 Copied memo `{memo_id}` to clipboard!")
            except Exception:
                pass

    elif action == "import":
        file_path = Path(args.file)
        if not file_path.is_file():
            print(f"❌ File not found: {file_path}")
            return

        title = getattr(args, "title", None) or file_path.stem.replace("_", " ").title()
        print(f"📥 Importing {file_path.name}...")

        is_audio = file_path.suffix.lower() in (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac")
        if is_audio:
            print("⏳ Transcribing imported audio...")
            stt = get_stt_engine(config)
            raw_speech = stt.transcribe(file_path)
        else:
            raw_speech = file_path.read_text(encoding="utf-8")

        if not raw_speech.strip():
            print("❌ No speech or text content found in file.")
            return

        print("🧠 Synthesizing Implementation Plan, Mermaid Diagram, and PR Checklist...\n")
        synthesizer = MemoSynthesizer(config)
        synthesis = synthesizer.synthesize(raw_speech=raw_speech, custom_title=title)

        recording = MemoRecording(
            id=synthesis.memo_id,
            title=synthesis.title,
            duration_seconds=0.0,
            target_duration_seconds=180.0,
            audio_path=str(file_path) if is_audio else None,
            raw_transcript=raw_speech,
            word_count=len(raw_speech.split()),
        )
        memo_dir = store.save_memo(recording, synthesis)
        print(f"💾 Imported and saved memo `{recording.id}` ({recording.title}) to {memo_dir}")
        print("\n" + "=" * 70)
        print(synthesis.to_markdown())
        print("=" * 70 + "\n")

    elif action == "delete":
        memo_id = args.memo_id
        if store.delete_memo(memo_id):
            print(f"🗑️ Deleted voice memo `{memo_id}`.")
        else:
            print(f"❌ Memo `{memo_id}` not found.")


