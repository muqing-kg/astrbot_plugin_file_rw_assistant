"""视频链接按需下载（yt-dlp）。只在用户问「这视频讲了什么」时调用，用完即删。"""

from __future__ import annotations

import subprocess
from pathlib import Path

FORMAT = "bv*[height<=720]+ba/b[height<=720]/b"


def fetch(url: str, out_dir: Path, cookies: str = "", max_mb: int = 2048) -> tuple[Path | None, str]:
    """下载视频到 out_dir，返回 (路径, 标题或失败原因)。

    cookies 可传 Netscape 格式原文，也可传本机文件路径。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp", "--no-playlist", "--no-warnings", "-q",
        "-f", FORMAT,
        "--max-filesize", f"{max_mb}M",
        "-o", str(out_dir / "%(id)s.%(ext)s"),
        "--print", "after_move:filepath",
        url,
    ]
    if cookies:
        jar = Path(cookies)
        if "\t" in cookies or "\n" in cookies:
            jar = out_dir / "cookies.txt"
            jar.write_text(cookies, encoding="utf-8")
        cmd[1:1] = ["--cookies", str(jar)]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        return None, "服务器没装 yt-dlp，无法解析视频链接。"
    except subprocess.TimeoutExpired:
        return None, "下载超时（超过 15 分钟）。"
    lines = [x.strip() for x in (done.stdout or "").splitlines() if x.strip()]
    path = Path(lines[-1]) if lines else None
    if done.returncode != 0 or not path or not path.exists():
        err = (done.stderr or "").strip().splitlines()
        return None, (err[-1] if err else "下载失败")[:300]
    size_mb = path.stat().st_size / 1048576
    if size_mb > max_mb:
        path.unlink(missing_ok=True)
        return None, f"视频 {size_mb:.0f}MB 超过 {max_mb}MB 上限。"
    return path, path.stem
