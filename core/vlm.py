"""视觉模型封装：把图片/视频抽帧变成文字描述。"""

from __future__ import annotations

import base64
import math
import os
import subprocess
import tempfile
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
    def __init__(
        self,
        provider_getter: Callable[[], Awaitable[object]],
        default_prompt: str = "",
    ):
        self._get_provider = provider_getter
        self.default_prompt = (default_prompt or "").strip()

    async def describe(
        self,
        images: list[bytes],
        *,
        prompt: str = "",
        audio: str = "",
    ) -> str:
        """images 是图片字节；audio 是音频 data URI。两者都为空的调用不该发生。"""
        if not images and not audio:
            return ""
        provider = await self._get_provider()
        if provider is None:
            return "（未配置视觉模型，跳过识图）"
        kwargs = {}
        if audio:
            kwargs["audio_urls"] = [audio]
        resp = await provider.text_chat(
            prompt=(prompt or self.default_prompt or PROMPT),
            image_urls=[_data_uri(img) for img in images] or None,
            system_prompt="你是文档识图助手。",
            **kwargs,
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


def frames_for(seconds: float, interval: float = 4, low: int = 4, high: int = 24) -> int:
    """按时长算帧数：每 interval 秒一帧，夹在 [low, high]。"""
    low = max(int(low), 1)
    high = max(int(high), low)
    if seconds <= 0 or interval <= 0:
        return low
    return max(low, min(high, math.ceil(seconds / interval)))


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


def extract_audio(path: Path, out_dir: Path, max_seconds: int = 300) -> str:
    """抽第一条音轨转 mp3 data URI；没有音轨或失败返回空串。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "audio.mp3"
    out.unlink(missing_ok=True)
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-t", str(max(int(max_seconds), 1)),
        "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", str(out),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=300, capture_output=True)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""
    if not out.exists() or out.stat().st_size == 0:
        return ""
    return _data_uri(out.read_bytes(), "audio/mp3")


def subtitle_text(path: Path, limit: int = 4000) -> str:
    """抽内嵌字幕轨转纯文本；没有字幕轨返回空串。"""
    probe = [
        "ffprobe", "-v", "error", "-select_streams", "s",
        "-show_entries", "stream=index", "-of", "csv=p=0", str(path),
    ]
    # ponytail: srt 复用器不支持写 stdout（会输出空文件），只能落到临时文件再读
    fd, name = tempfile.mkstemp(suffix=".srt")
    out = Path(name)
    try:
        os.close(fd)
        if not (subprocess.run(probe, capture_output=True, text=True, timeout=30).stdout or "").strip():
            return ""
        done = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-map", "0:s:0", "-f", "srt", str(out)],
            capture_output=True, text=True, timeout=120,
        )
        if done.returncode != 0 or not out.exists():
            return ""
        text = out.read_text(encoding="utf-8", errors="replace")
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""
    finally:
        out.unlink(missing_ok=True)
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        # srt 的序号行与时间轴行都不是台词
        if not line or line.isdigit() or "-->" in line:
            continue
        lines.append(line)
    return "\n".join(lines)[:limit]
