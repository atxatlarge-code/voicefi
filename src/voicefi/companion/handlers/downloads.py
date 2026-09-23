"""
Companion route handlers for static assets, downloads, and file management.
"""

import time
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional
from aiohttp import web


def get_safe_download_path(downloads_dir: Path, filename: str) -> Optional[Path]:
    downloads_dir = downloads_dir.resolve()
    downloads_dir.mkdir(parents=True, exist_ok=True)
    decoded = urllib.parse.unquote(filename)
    clean_name = Path(decoded).name
    if not clean_name or clean_name in (".", ".."):
        return None
    target = (downloads_dir / clean_name).resolve()
    if not target.is_relative_to(downloads_dir):
        return None
    return target



def classify_download_file(p: Path) -> Dict[str, Any]:
    stat = p.stat()
    ext = p.suffix.lower()
    size_bytes = stat.st_size

    if size_bytes < 1024:
        formatted_size = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        formatted_size = f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        formatted_size = f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        formatted_size = f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    video_exts = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}
    audio_exts = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".aiff"}
    doc_exts = {".md", ".txt", ".pdf", ".rtf", ".doc", ".docx"}
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
    code_exts = {".json", ".csv", ".yaml", ".yml", ".html", ".css", ".js", ".py", ".sh", ".ts"}
    editable_exts = {
        ".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".html", ".css",
        ".js", ".py", ".sh", ".ts", ".xml", ".log", ".tsv", ".ini", ".conf",
    }

    category = "other"
    if ext in video_exts:
        category = "video"
    elif ext in audio_exts:
        category = "audio"
    elif ext in image_exts:
        category = "image"
    elif ext in doc_exts or ext in code_exts:
        category = "document"

    return {
        "name": p.name,
        "size": size_bytes,
        "formatted_size": formatted_size,
        "mtime": stat.st_mtime,
        "mtime_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        "ext": ext,
        "category": category,
        "editable": ext in editable_exts,
        "playable": ext in video_exts or ext in audio_exts,
        "url": f"/downloads/{p.name}",
    }


async def handle_downloads_list(downloads_dir: Path) -> web.Response:
    downloads_dir = downloads_dir.resolve()
    downloads_dir.mkdir(parents=True, exist_ok=True)
    files = []
    total_size = 0
    for item in downloads_dir.iterdir():
        if item.name.startswith(".") or not item.is_file():
            continue
        f_info = classify_download_file(item)
        files.append(f_info)
        total_size += f_info["size"]

    files.sort(key=lambda x: x["mtime"], reverse=True)

    if total_size < 1024 * 1024:
        total_formatted = f"{total_size / 1024:.1f} KB"
    elif total_size < 1024 * 1024 * 1024:
        total_formatted = f"{total_size / (1024 * 1024):.1f} MB"
    else:
        total_formatted = f"{total_size / (1024 * 1024 * 1024):.2f} GB"

    return web.json_response({
        "status": "ok",
        "files": files,
        "total_count": len(files),
        "total_size": total_size,
        "total_size_formatted": total_formatted,
    })
