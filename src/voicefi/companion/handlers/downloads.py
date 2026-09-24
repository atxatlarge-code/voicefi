"""
Companion route handlers for static assets, downloads, and file management.
"""

import time
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional
from aiohttp import web

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PROJECT_ROOT = Path(__file__).resolve().parents[4]


def get_safe_download_path(downloads_dir: Path, filename: str) -> Optional[Path]:
    downloads_dir = downloads_dir.resolve()
    downloads_dir.mkdir(parents=True, exist_ok=True)
    decoded = urllib.parse.unquote(filename)
    clean_name = Path(decoded).name
    if not clean_name or clean_name in (".", ".."):
        return None
    target = (downloads_dir / clean_name).resolve()
    if not str(target).startswith(str(downloads_dir)):
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
        ".md",
        ".txt",
        ".json",
        ".csv",
        ".yaml",
        ".yml",
        ".html",
        ".css",
        ".js",
        ".py",
        ".sh",
        ".ts",
        ".xml",
        ".log",
        ".tsv",
        ".ini",
        ".conf",
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

    return web.json_response(
        {
            "status": "ok",
            "files": files,
            "total_count": len(files),
            "total_size": total_size,
            "total_size_formatted": total_formatted,
        }
    )


class DownloadsHandlersMixin:
    """Mixin providing downloads page, file streaming, and CRUD management handlers."""

    def _safe_download_path(self, filename: str) -> Optional[Path]:
        downloads_dir = (STATIC_DIR / "downloads").resolve()
        return get_safe_download_path(downloads_dir, filename)

    def _classify_download_file(self, p: Path) -> Dict[str, Any]:
        return classify_download_file(p)

    async def handle_downloads(self, request: web.Request) -> web.Response:
        downloads_path = STATIC_DIR / "downloads.html"
        if not downloads_path.is_file():
            return web.Response(text="Downloads page missing.", status=404)
        return web.Response(
            text=downloads_path.read_text(encoding="utf-8"),
            content_type="text/html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    async def handle_download_file(self, request: web.Request) -> web.StreamResponse:
        filename = request.match_info.get("filename")
        if not filename:
            return web.Response(text="Filename missing.", status=400)

        decoded = urllib.parse.unquote(filename)
        file_path = STATIC_DIR / "downloads" / decoded
        if not file_path.is_file():
            file_path = STATIC_DIR / "downloads" / filename
        if not file_path.is_file():
            alt_path = PROJECT_ROOT / decoded
            if alt_path.is_file():
                file_path = alt_path
            else:
                return web.Response(text=f"File {filename} not found.", status=404)

        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Range",
            "Accept-Ranges": "bytes",
        }
        if request.query.get("download") == "1":
            headers["Content-Disposition"] = f'attachment; filename="{decoded}"'
        else:
            headers["Content-Disposition"] = f'inline; filename="{decoded}"'

        return web.FileResponse(file_path, headers=headers)

    async def handle_spicewood_sheet(self, request: web.Request) -> web.Response:
        sheet_path = STATIC_DIR / "downloads" / "spicewood_texas_lead_sheet.md"
        if not sheet_path.is_file():
            sheet_path = PROJECT_ROOT / "spicewood_texas_lead_sheet.md"
        if not sheet_path.is_file():
            return web.json_response({"error": "Spicewood lead sheet not found"}, status=404)
        content = sheet_path.read_text(encoding="utf-8")
        return web.json_response(
            {
                "title": "Spicewood, Texas",
                "bpm": 85,
                "filename": "spicewood_texas_lead_sheet.md",
                "content": content,
            }
        )

    async def handle_api_downloads_list(self, request: web.Request) -> web.Response:
        downloads_dir = (STATIC_DIR / "downloads").resolve()
        downloads_dir.mkdir(parents=True, exist_ok=True)
        files = []
        total_size = 0
        for item in downloads_dir.iterdir():
            if item.name.startswith(".") or not item.is_file():
                continue
            f_info = self._classify_download_file(item)
            files.append(f_info)
            total_size += f_info["size"]

        files.sort(key=lambda x: x["mtime"], reverse=True)

        if total_size < 1024 * 1024:
            total_formatted = f"{total_size / 1024:.1f} KB"
        elif total_size < 1024 * 1024 * 1024:
            total_formatted = f"{total_size / (1024 * 1024):.1f} MB"
        else:
            total_formatted = f"{total_size / (1024 * 1024 * 1024):.2f} GB"

        return web.json_response(
            {
                "status": "ok",
                "files": files,
                "total_count": len(files),
                "total_size": total_size,
                "total_size_formatted": total_formatted,
            }
        )

    async def handle_api_downloads_get_content(self, request: web.Request) -> web.Response:
        filename = request.match_info.get("filename", "")
        target = self._safe_download_path(filename)
        if not target or not target.is_file():
            return web.json_response({"error": "File not found"}, status=404)
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            info = self._classify_download_file(target)
            return web.json_response(
                {
                    "status": "ok",
                    "filename": target.name,
                    "content": content,
                    "info": info,
                }
            )
        except Exception as e:
            return web.json_response({"error": f"Failed to read file: {e}"}, status=400)

    async def handle_api_downloads_save_content(self, request: web.Request) -> web.Response:
        filename = request.match_info.get("filename", "")
        target = self._safe_download_path(filename)
        if not target:
            return web.json_response({"error": "Invalid filename"}, status=400)
        try:
            data = await request.json()
            content = data.get("content", "")
            target.write_text(content, encoding="utf-8")
            info = self._classify_download_file(target)
            return web.json_response(
                {
                    "status": "ok",
                    "filename": target.name,
                    "info": info,
                }
            )
        except Exception as e:
            return web.json_response({"error": f"Failed to save file: {e}"}, status=500)

    async def handle_api_downloads_upload(self, request: web.Request) -> web.Response:
        downloads_dir = (STATIC_DIR / "downloads").resolve()
        downloads_dir.mkdir(parents=True, exist_ok=True)
        uploaded = []
        try:
            content_type = request.headers.get("Content-Type", "")
            if "multipart" in content_type:
                reader = await request.multipart()
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    raw_filename = part.filename
                    if not raw_filename:
                        continue
                    clean_name = Path(raw_filename).name
                    target = (downloads_dir / clean_name).resolve()
                    if not str(target).startswith(str(downloads_dir)):
                        continue
                    with open(target, "wb") as f:
                        while True:
                            chunk = await part.read_chunk()
                            if not chunk:
                                break
                            f.write(chunk)
                    uploaded.append(self._classify_download_file(target))
            else:
                data = await request.json()
                filename = data.get("filename")
                if not filename:
                    return web.json_response({"error": "Missing filename"}, status=400)
                clean_name = Path(filename).name
                target = (downloads_dir / clean_name).resolve()
                if not str(target).startswith(str(downloads_dir)):
                    return web.json_response({"error": "Invalid target path"}, status=400)

                if "content_base64" in data:
                    import base64

                    b64 = data["content_base64"]
                    if "," in b64:
                        b64 = b64.split(",", 1)[1]
                    target.write_bytes(base64.b64decode(b64))
                elif "content" in data:
                    target.write_text(data["content"], encoding="utf-8")
                else:
                    return web.json_response({"error": "Missing file content"}, status=400)
                uploaded.append(self._classify_download_file(target))

            return web.json_response(
                {
                    "status": "ok",
                    "uploaded": uploaded,
                }
            )
        except Exception as e:
            return web.json_response({"error": f"Upload failed: {e}"}, status=500)

    async def handle_api_downloads_rename(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            old_name = data.get("old_name", "")
            new_name = data.get("new_name", "")
            if not old_name or not new_name:
                return web.json_response({"error": "old_name and new_name required"}, status=400)

            src = self._safe_download_path(old_name)
            dst = self._safe_download_path(new_name)
            if not src or not src.is_file():
                return web.json_response({"error": "Source file not found"}, status=404)
            if not dst:
                return web.json_response({"error": "Invalid destination filename"}, status=400)
            if dst.exists() and dst != src:
                return web.json_response({"error": "Destination file already exists"}, status=409)

            src.rename(dst)
            return web.json_response(
                {
                    "status": "ok",
                    "file": self._classify_download_file(dst),
                }
            )
        except Exception as e:
            return web.json_response({"error": f"Rename failed: {e}"}, status=500)

    async def handle_api_downloads_delete(self, request: web.Request) -> web.Response:
        filename = request.match_info.get("filename", "")
        target = self._safe_download_path(filename)
        if not target or not target.is_file():
            return web.json_response({"error": "File not found"}, status=404)
        try:
            target.unlink()
            return web.json_response(
                {
                    "status": "ok",
                    "deleted": target.name,
                }
            )
        except Exception as e:
            return web.json_response({"error": f"Failed to delete file: {e}"}, status=500)
