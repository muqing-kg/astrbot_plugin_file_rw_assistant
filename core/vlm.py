"""视觉模型封装：把图片/视频抽帧变成文字描述。"""

from __future__ import annotations

import base64
import math
import re
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


def fill(template: str, **values: object) -> str:
    """把模板里的 {name} 换成给定值；不认识的花括号原样留着，别让它报错。"""
    if not template:
        return ""

    def sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        return str(values[key]) if key in values else m.group(0)

    return re.sub(r"\{(\w+)\}", sub, template)


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
            prompt=fill(prompt or self.default_prompt or PROMPT, count=len(images)),
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


def _scene_frames(path: Path, out_dir: Path, count: int) -> tuple[list[Path], list[float]]:
    """按场景切换挑关键帧，附带每帧的真实时间点。"""
    for old in out_dir.glob("*.jpg"):
        old.unlink(missing_ok=True)
    pattern = out_dir / "s_%03d.jpg"
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-vf", "select='gt(scene,0.3)',showinfo,scale=1024:-2",
        "-vsync", "vfr", "-frames:v", str(count), str(pattern),
    ]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        return [], []
    # showinfo 每帧打一行到 stderr，形如 n:0 pts:... pts_time:12.345
    stamps = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", done.stderr or "")]
    files = sorted(out_dir.glob("s_*.jpg"))[:count]
    return files, stamps[: len(files)]


def _even_frames(path: Path, out_dir: Path, count: int, seconds: float) -> tuple[list[Path], list[float]]:
    """全长均匀抽帧，时间点按帧率推算。"""
    for old in out_dir.glob("*.jpg"):
        old.unlink(missing_ok=True)
    pattern = out_dir / "f_%03d.jpg"
    # 时长撑不起 count 帧时退化成每秒一帧，否则按全长均分
    fps = count / seconds if seconds > count else 1.0
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-vf", f"fps={fps:.4f},scale=1024:-2", "-frames:v", str(count),
        str(pattern),
    ]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        return [], []
    files = sorted(out_dir.glob("f_*.jpg"))[:count]
    return files, [round((i + 0.5) / fps, 1) for i in range(len(files))]


def video_frames(path: Path, out_dir: Path, count: int = 8) -> tuple[list[bytes], list[float]]:
    """抽帧，返回 (JPEG 字节, 每帧所在秒数)。优先场景切换，静态画面退回均匀抽帧。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink(missing_ok=True)
    count = max(count, 1)
    seconds = duration_of(path)
    try:
        files, times = _scene_frames(path, out_dir, count)
        # 场景帧太少（固定机位、静态画面）就没代表性，退回均匀抽帧
        if len(files) < max(2, count // 2):
            files, times = _even_frames(path, out_dir, count, seconds)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return [], []
    return [f.read_bytes() for f in files], times


def extract_audio(path: Path, out_dir: Path, max_seconds: int = 300) -> tuple[str, float]:
    """抽第一条音轨转 mp3 data URI，返回 (data URI, 实际截取的秒数)。失败返回 ("", 0)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "audio.mp3"
    out.unlink(missing_ok=True)
    limit = max(int(max_seconds), 1)
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-t", str(limit),
        "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(out),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=300, capture_output=True)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return "", 0.0
    if not out.exists() or out.stat().st_size == 0:
        return "", 0.0
    covered = min(duration_of(out) or limit, float(limit))
    return _data_uri(out.read_bytes(), "audio/mp3"), round(covered, 1)


def _cues(srt: str, limit: int) -> str:
    """srt 文本 → `[分:秒] 台词`，超长截断。"""
    out: list[str] = []
    stamp = ""
    for raw in srt.splitlines():
        line = raw.strip()
        if "-->" in line:
            try:
                hh, mm, ss = line.split("-->")[0].strip().replace(",", ":").split(":")[:3]
                total = int(hh) * 3600 + int(mm) * 60 + int(float(ss))
                stamp = f"[{total // 60:02d}:{total % 60:02d}]"
            except (ValueError, IndexError):
                stamp = ""
            continue
        if not line or line.isdigit():
            continue
        out.append(f"{stamp} {line}".strip() if stamp else line)
    return "\n".join(out)[:limit]


def subtitle_text(path: Path, limit: int = 4000) -> str:
    """抽内嵌字幕轨（带时间轴）；逐条轨试，取第一条有文字的。没有返回空串。"""
    probe = [
        "ffprobe", "-v", "error", "-select_streams", "s",
        "-show_entries", "stream=index", "-of", "csv=p=0", str(path),
    ]
    try:
        raw = subprocess.run(probe, capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""
    tracks = [t.strip() for t in (raw.stdout or "").split() if t.strip()]
    for track in tracks:
        # ponytail: srt 复用器不支持写 stdout（会输出空文件），只能落到临时文件再读
        fd, name = tempfile.mkstemp(suffix=".srt")
        out = Path(name)
        os.close(fd)
        try:
            done = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(path),
                 "-map", f"0:s:{track}", "-f", "srt", str(out)],
                capture_output=True, text=True, timeout=120,
            )
            if done.returncode != 0 or not out.exists():
                continue
            text = _cues(out.read_text(encoding="utf-8", errors="replace"), limit)
        except (subprocess.SubprocessError, OSError):
            continue
        finally:
            out.unlink(missing_ok=True)
        if text:
            return text
    return ""
