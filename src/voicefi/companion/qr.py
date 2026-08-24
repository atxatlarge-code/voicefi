"""
Network utilities and QR code generation for the VoiceFi Mobile Companion.
Provides local LAN discovery, pairing URL generation, and terminal/ASCII QR display.
"""

import io
import socket
import base64
from typing import List, Dict, Any, Optional


def get_local_ip() -> str:
    """
    Determine the primary local LAN IP address of the machine.
    Uses UDP socket probe to avoid DNS lookup delays.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't actually send packets; determines routing interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def get_mdns_hostname() -> str:
    """Return local mDNS hostname (e.g. jakes-mac.local)."""
    try:
        hostname = socket.gethostname()
        if not hostname.endswith(".local") and "." not in hostname:
            return f"{hostname}.local"
        return hostname
    except Exception:
        return "localhost"


def get_companion_urls(port: int = 8765) -> Dict[str, str]:
    """Get all candidate URLs for pairing with the mobile companion and studio."""
    ip = get_local_ip()
    mdns = get_mdns_hostname()
    https_port = port + 1
    return {
        "ip_url": f"http://{ip}:{port}",
        "https_ip_url": f"https://{ip}:{https_port}",
        "mdns_url": f"http://{mdns}:{port}",
        "https_mdns_url": f"https://{mdns}:{https_port}",
        "localhost_url": f"http://localhost:{port}",
        "https_localhost_url": f"https://localhost:{https_port}",
        "studio_ip_url": f"http://{ip}:{port}/studio",
        "studio_localhost_url": f"http://localhost:{port}/studio",
    }


def generate_qr_ascii(data: str) -> str:
    """Generate ASCII art representation of QR code for terminal display."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)

        f = io.StringIO()
        qr.print_ascii(out=f, invert=True)
        return f.getvalue()
    except Exception:
        # Fallback if qrcode library cannot render
        return f"[QR Code: {data}]"


def generate_qr_base64_png(data: str) -> str:
    """
    Generate base64-encoded PNG or SVG data URI of QR code for web / HUD display.
    Gracefully falls back from Pillow PNG to zero-dependency SVG output.
    """
    # Attempt 1: Pillow PNG export
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        pass

    # Attempt 2: Pure SVG export (requires only qrcode without Pillow)
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
            image_factory=SvgPathImage,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image()
        buf = io.BytesIO()
        img.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{b64}"
    except Exception:
        pass

    return ""


def print_qr_code(url: str, title: str = "VoiceFi Mobile Companion") -> None:
    """Print a visually polished QR code banner in the terminal."""
    ascii_qr = generate_qr_ascii(url)
    print("\n" + "=" * 54)
    print(f"  🎙️  {title}")
    print("=" * 54)
    print("\nScan this QR code with your Android phone or iPhone camera:")
    print(ascii_qr)
    print(f"🔗 Direct URL: {url}")
    print("📱 Tip: On Android Chrome, tap 'Add to Home Screen' to install as an App!")
    print("=" * 54 + "\n")
