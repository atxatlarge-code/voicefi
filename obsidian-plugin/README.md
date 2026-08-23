# VoiceFi Obsidian Plugin 🎙️

**Second Brain, Second Voice.** The vocal cords for your vault.

This plugin seamlessly integrates [VoiceFi](https://voicefi.org) into Obsidian, bringing native speech-to-text dictation, intelligent active listening loops, and Text-to-Speech (TTS) reading directly to your markdown notes.

## Features

- **Hands-Free Active Listening**: Toggle the microphone directly from the Obsidian ribbon. Pace the room while your thoughts are transcribed directly into your active note.
- **Read Notes Aloud**: Highlight any text (or an entire note) and trigger the "Speak Current Note" command. VoiceFi will use its local TTS engine to read the contents to you.
- **Agent Integration (Coming Soon)**: Dispatch your voice notes to your background AI coding agents directly from the Obsidian editor.

## Setup Instructions

1. Ensure the VoiceFi CLI (`vifi`) is installed and accessible on your machine.
2. Run `npm install` and `npm run build` in this directory to build the plugin.
3. Copy the entire `obsidian-plugin` folder into your vault's `.obsidian/plugins/` directory, and rename the folder to `voicefi`.
4. Enable the plugin in Obsidian's Community Plugins settings.
5. *(Optional)* Start the VoiceFi companion server (`vifi companion`) if using the live WebSocket connection for Active Listening.

## Settings

- **CLI Path**: If `vifi` is not in your global path, specify the absolute path to the binary (e.g. `~/.local/bin/vifi` or your `uv` virtual environment).
- **Audio Cues**: Enable or disable the system chimes that play when listening starts/stops.
