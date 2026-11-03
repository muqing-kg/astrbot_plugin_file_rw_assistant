"""把文件发回当前会话。三层：平台直发 → File 组件 → 只回提示。"""

from __future__ import annotations

from pathlib import Path

try:
    from astrbot.api.event import MessageChain
    from astrbot.api.message_components import File as FileComp
except ImportError:  # 单测环境没有框架
    MessageChain = None  # type: ignore[assignment]
    FileComp = None  # type: ignore[assignment]


async def send_file(
    event, path: Path, name: str | None = None, max_mb: int = 100
) -> str:
    """返回一句话说明结果，交给模型转述。"""
    if not path.exists():
        return f"发送失败：本地文件不存在（{path.name}）"
    size_mb = path.stat().st_size / (1024 * 1024)
    if max_mb and size_mb > max_mb:
        return (
            f"文件 {name or path.name} 有 {size_mb:.1f}MB，超过发回上限 {max_mb}MB，"
            f"没有发送；需要的话在面板里下载"
        )
    if MessageChain is None or FileComp is None:
        return f"发送失败：框架组件不可用，文件在 {path}"

    try:
        chain = MessageChain(chain=[FileComp(name=name or path.name, file=str(path))])
        await event.send(chain)
        return f"已发送文件：{name or path.name}"
    except Exception as exc:
        # ponytail: 平台不发文件就只回提示；要真·跨平台直发再按平台写适配
        return (
            f"当前平台直发文件失败（{type(exc).__name__}: {exc}），"
            f"文件已在文件读写小助手：{name or path.name}"
        )
