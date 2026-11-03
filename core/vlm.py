"""视觉模型封装：把图片/视频抽帧变成文字描述。"""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path
from typing import Awaitable, Callable

from . import readers

MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

PROMPT = (
    "逐张描述这些图片里能读到的内容。有文字就照抄关键文字与原意，"
    "是表格就还原成文字表格，是界面就说明在讲什么。不要寒暄，不要复述指令。"
)


def _data_uri(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


class Vision:
    def __init__(self, provider_getter: Callable[[], Awaitable[object]]):
        self._get_provider = provider_getter

    async def describe(self, images: list[bytes]) -> str:
        if not images:
            return ""
        provider = await self._get_provider()
        if provider is None:
            return "（未配置视觉模型，跳过识图）"
        resp = await provider.text_chat(
            prompt=PROMPT,
            image_urls=[_data_uri(img) for img in images],
            system_prompt="你是文档识图助手。",
        )
        return (getattr(resp, "completion_text", "") or "").strip()

    async def describe_files(self, path: Path, limit: int = 6) -> str:
        shots = readers.embedded_images(path, limit)
        if not shots:
            return "（没有可识别的图片内容）"
        return await self.describe(shots)


def duration_of(path: Path) -> float:
    """秒数，取不到当 0。"""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float((done.stdout or "0").strip() or 0)
    except (subprocess.SubprocessError, FileNotFoundError, OSError, ValueError):
        return 0.0


def video_frames(path: Path, out_dir: Path, count: int = 8) -> list[bytes]:
    """按全长均匀抽帧，返回 JPEG 字节。失败返回空列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.jpg"):
        old.unlink(missing_ok=True)
    pattern = out_dir / "f_%03d.jpg"
    count = max(count, 1)
    seconds = duration_of(path)
    # 时长撑不起 count 帧时退化成每秒一帧，否则按全长均分
    fps = f"{count / seconds:.4f}" if seconds > count else "1"
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-vf", f"fps={fps},scale=1024:-2", "-frames:v", str(count),
        str(pattern),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=300, capture_output=True)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return []
    frames = sorted(out_dir.glob("f_*.jpg"))[:count]
    return [f.read_bytes() for f in frames]
