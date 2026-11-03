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


def video_frames(path: Path, out_dir: Path, count: int = 8) -> list[bytes]:
    """ffmpeg 均匀抽帧，返回 JPEG 字节。失败返回空列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "f_%03d.jpg"
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-vf", f"fps=1/2,scale=1024:-2", "-frames:v", str(max(count, 1)),
        str(pattern),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=120, capture_output=True)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        # ponytail: 只试一次 fps=1/2；长视频想要均匀分布再按 duration 计算，别现在加
        return []
    frames = sorted(out_dir.glob("f_*.jpg"))[:count]
    return [f.read_bytes() for f in frames]
