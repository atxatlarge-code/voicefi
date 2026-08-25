"""
VoiceFi Robust Local Development & Neural TTS Server
Serves static website assets and real-time 48kHz neural Edge TTS stream at http://localhost:8000
"""
import io
import os
import sys
import json
import urllib.parse
import asyncio
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import edge_tts

VOICE_MAP = {
    "viv": "en-US-AvaNeural",
    "ava": "en-US-AvaNeural",
    "emily": "en-IE-EmilyNeural",
    "christopher": "en-US-ChristopherNeural",
    "aria": "en-US-AriaNeural",
    "sonia": "en-GB-SoniaNeural",
    "guy": "en-US-GuyNeural",
}

async def generate_edge_tts(voice: str, text: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    audio_stream = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_stream.write(chunk["data"])
    return audio_stream.getvalue()

class VoiceFiHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="website", **kwargs)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        
        # Route: /api/tts
        if parsed.path == "/api/tts":
            query = urllib.parse.parse_qs(parsed.query)
            voice_key = query.get("voice", ["viv"])[0].lower()
            voice = VOICE_MAP.get(voice_key, "en-US-AvaNeural")
            text = query.get("text", ["VoiceFi ambient voice protocol ready."])[0]

            if not text.strip():
                self.send_error(400, "Empty text parameter")
                return

            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                audio_bytes = loop.run_until_complete(generate_edge_tts(voice, text))
                loop.close()

                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(audio_bytes)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(audio_bytes)
                return
            except Exception as e:
                self.send_error(500, f"Edge TTS Error: {str(e)}")
                return

        # Route: /vifi.sh, /install.sh, or curl root request
        if parsed.path in ["/vifi.sh", "/install.sh"] or (parsed.path == "/" and "curl" in self.headers.get("User-Agent", "").lower()):
            install_script_path = os.path.join("website", "install.sh")
            if not os.path.exists(install_script_path):
                install_script_path = "install.sh"
            if os.path.exists(install_script_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with open(install_script_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        # Route: /assets/
        if parsed.path.startswith("/assets/"):
            asset_subpath = parsed.path[len("/assets/"):]
            local_asset_path = os.path.join("assets", asset_subpath)
            if os.path.exists(local_asset_path):
                self.send_response(200)
                if local_asset_path.endswith(".svg"):
                    self.send_header("Content-Type", "image/svg+xml")
                elif local_asset_path.endswith(".png"):
                    self.send_header("Content-Type", "image/png")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with open(local_asset_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        # Default static file handler in website/
        super().do_GET()

if __name__ == "__main__":
    PORT = 8000
    server = ThreadingHTTPServer(("0.0.0.0", PORT), VoiceFiHTTPHandler)
    print(f"🚀 VoiceFi Neural Web Server running at:")
    print(f"   • Local:   http://localhost:{PORT}")
    print(f"   • Network: http://192.168.1.60:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
