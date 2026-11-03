"""文件读写小助手：聊天文件归档、版本历史、读写解析、改写生成与面板管理。"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File as FileComp
from astrbot.api.star import Context, Star, register
from astrbot.api.web import file_response, json_response
from astrbot.api.web import request as web_request

from .core import links, readers, writers
from .core.sender import send_file
from .core.store import KINDS, FileStore, human_size, kind_of
from .core.vlm import Vision, video_frames

PLUGIN_NAME = "astrbot_plugin_file_rw_assistant"
REPO = "https://github.com/muqing-kg/astrbot_plugin_file_rw_assistant"
KIND_LABELS = {
    "word": "Word", "excel": "Excel", "ppt": "PPT", "pdf": "PDF",
    "text": "文本", "markdown": "Markdown", "code": "代码", "csv": "CSV",
    "video": "视频",
}
FILE_KINDS = set(KINDS)


@register(PLUGIN_NAME, "沐倾", "文件读写小助手", "1.2.2", REPO)
class FileAssistant(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.vision = Vision(self._vision_provider)
        self._cleaner: asyncio.Task | None = None
        self._register_web_api()

    # ── 生命周期 ─────────────────────────────────────────────
    def _root(self) -> Path:
        from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

        base = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        base.mkdir(parents=True, exist_ok=True)
        return base

    @property
    def store(self) -> FileStore:
        if not hasattr(self, "_store"):
            self._store = FileStore(
                self._root(),
                retention_days=int(self.config.get("retention_days") or 90),
                max_versions=int(self.config.get("max_versions") or 20),
            )
        return self._store

    async def initialize(self) -> None:
        self.store
        if self.config.get("auto_cleanup", True):
            self._cleaner = asyncio.create_task(self._cleanup_loop())
        logger.info(f"[文件读写小助手] 已就绪，存储于 {self._root()}")

    async def terminate(self) -> None:
        if self._cleaner:
            self._cleaner.cancel()
        logger.info("[文件读写小助手] 已卸载")

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(6 * 3600)
                result = self.store.purge()
                if result["expired"] or result["temp"]:
                    logger.info(f"[文件读写小助手] 清理完成：{result}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"[文件读写小助手] 清理失败：{exc}")

    # ── 模型选择 ─────────────────────────────────────────────
    async def _provider_by(self, key: str):
        pid = str(self.config.get(key) or "").strip()
        try:
            if pid:
                provider = self.context.get_provider_by_id(pid)
                if provider:
                    return provider
            return await self.context.get_using_provider_async()
        except Exception as exc:
            logger.warning(f"[文件读写小助手] 取模型失败（{key}）：{exc}")
            return None

    async def _vision_provider(self):
        return await self._provider_by("vision_model_provider_id")

    async def _condense(self, text: str, provider_id: str) -> str:
        """长正文先过一遍配置的文本模型，免得整篇灌进对话上下文。"""
        provider = self.context.get_provider_by_id(provider_id)
        if provider is None:
            return text
        try:
            brief = await provider.text_chat(
                prompt=f"把下面的文档正文压缩成不超过 800 字的要点，数字、名称、结论必须保留：\n\n{text[:60000]}",
                system_prompt="你是文档摘要器，只输出要点，不加评论，不寒暄。",
            )
            return f"【摘要】{brief}\n\n【原文开头】{text[:2000]}"
        except Exception as exc:
            logger.warning(f"[文件读写小助手] 摘要失败：{exc}")
            return text

    # ── 入库 ─────────────────────────────────────────────────
    def _limit_mb(self, kind: str) -> int:
        if kind == "video":
            return int(self.config.get("max_video_mb") or 2048)
        return int(self.config.get("max_file_mb") or 200)

    def _ingest(self, path: Path, name: str, session: str, sender: str) -> dict[str, Any]:
        kind = kind_of(name) or kind_of(path.name)
        if not kind or kind not in FILE_KINDS:
            raise ValueError(f"不收这类文件：{Path(name).suffix or name}")
        size_mb = path.stat().st_size / 1048576
        if size_mb > self._limit_mb(kind):
            raise ValueError(f"文件 {size_mb:.0f}MB 超过 {self._limit_mb(kind)}MB 上限")
        return self.store.add(name=name, session=session, src=path, sender=sender)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def on_file_message(self, event: AstrMessageEvent):
        """聊天里出现文件就入库，并把入库结果告诉模型。"""
        comps = [c for c in event.message_obj.message if isinstance(c, FileComp)]
        if not comps:
            return
        session = event.unified_msg_origin
        sender = event.get_sender_name() or event.get_sender_id() or ""
        notes = []
        for comp in comps:
            name = comp.name or "file"
            try:
                path = Path(await comp.get_file())
                if not path.exists():
                    notes.append(f"{name}：下载失败")
                    continue
                rec = self._ingest(path, name, session, sender)
                notes.append(
                    f"{rec['name']}（id={rec['id']}，{human_size(rec['size'])}，"
                    f"类型={KIND_LABELS.get(rec['kind'], rec['kind'])}）"
                )
            except Exception as exc:
                notes.append(f"{name}：{exc}")
        if notes:
            marker = "\n[文件读写小助手] " + "；".join(notes)
            try:
                event.message_str = (event.message_str or "") + marker
            except Exception:
                logger.info(f"[文件读写小助手] 入库：{'; '.join(notes)}")

    # ── 工具：列 / 读 / 写 / 发 / PDF / 视频链接 ─────────────
    @filter.llm_tool(name="file_list")
    async def file_list(
        self,
        event: AstrMessageEvent,
        kind: str = "",
        keyword: str = "",
        sender: str = "",
        days: int = 0,
    ):
        """列出文件读写小助手里的文件。用户问「有哪些文件」「前几天发的那个」时调用。

        Args:
            kind(string): 类型，可选 word/excel/ppt/pdf/text/markdown/code/csv/video，留空表示全部
            keyword(string): 文件名或备注关键词
            sender(string): 发送人昵称，留空不限
            days(number): 只看最近几天更新过的，0 表示不限
        """
        kind = (kind or "").strip().lower()
        items = self.store.search(
            kind=kind or None,
            query=keyword or "",
            sender=sender or "",
            session=event.unified_msg_origin if not (sender or keyword) else "",
            days=int(days or 0),
        )
        if not items:
            return "文件读写小助手里没有符合条件的文件。"
        lines = [
            f"{i['name']} | id={i['id']} | {KIND_LABELS.get(i['kind'], i['kind'])} | "
            f"{human_size(i['size'])} | v{i['current_version']} | {i['updated_at']} | "
            f"{i['sender'] or '未知'}"
            for i in items[:40]
        ]
        return "文件读写小助手（最多显示 40 条）：\n" + "\n".join(lines)

    @filter.llm_tool(name="file_read")
    async def file_read(
        self,
        event: AstrMessageEvent,
        file_id: str,
        version: int = 0,
        pages: str = "",
        lines: str = "",
        find: str = "",
    ):
        """读取文件内容。用户问某个文件里写了什么、要总结、或要查某处内容时调用。

        Args:
            file_id(string): 文件 id，或文件名关键词
            version(number): 指定版本号，0 表示最新版
            pages(string): PDF 只看这些页，如 "30" 或 "30-32"
            lines(string): 文本类只看这些行，如 "100-200"
            find(string): 关键词，只回命中的行（找长文档里的某段内容时用它，别整篇读）
        """
        rec = self._resolve(file_id)
        if not rec:
            return f"没找到文件：{file_id}"
        path = self._path_of(rec, version)
        if not path.exists():
            return f"文件不存在：{path.name}"
        if rec["kind"] == "video":
            return await self._describe_video(path, rec["name"])
        text = await readers.read(
            path,
            ocr=bool(self.config.get("enable_pdf_ocr", True)),
            vision=self.vision,
            pages=pages or "",
            lines=lines or "",
            find=find or "",
        )
        pid = str(self.config.get("text_model_provider_id") or "").strip()
        if pid and len(text) > 6000:
            text = await self._condense(text, pid)
        return f"《{rec['name']}》第 {version or rec['current_version']} 版内容：\n{text}"

    @filter.llm_tool(name="file_write")
    async def file_write(self, event: AstrMessageEvent, file_id: str, content: str = "", ops: str = ""):
        """改写已有文件并存成新版本。文本类用 content 全量替换；Excel/PPT/Word 用 ops 就地改，版式不动。

        Args:
            file_id(string): 文件 id 或文件名关键词
            content(string): 文本类文件的完整新内容
            ops(string): Office 就地改动的 JSON 数组。Excel 例 [{"sheet":"Sheet1","cell":"B2","value":12}]；PPT 例 [{"slide":1,"shape":1,"text":"新标题"}]；Word 例 [{"paragraph":2,"text":"新内容"}]
        """
        rec = self._resolve(file_id)
        if not rec:
            return f"没找到文件：{file_id}"
        path = self._path_of(rec)
        if rec["kind"] == "video":
            return "视频不支持改写。"
        if rec["kind"] == "pdf":
            return "PDF 用 file_pdf：keep 只留指定页，pages 按页渲染看版式。改正文请用 file_new 重写一份。"
        try:
            if writers.is_textual(path) and content:
                new = self.store.add_version(rec["id"], data=content.encode("utf-8"), note="模型改写")
                return f"已存成第 {new['current_version']} 版：{new['name']}（id={new['id']}）"
            if ops:
                import json as _json

                parsed = _json.loads(ops) if isinstance(ops, str) else ops
                # 在临时副本上改：直接改当前版本文件会把旧版本内容一起冲掉，回滚就回不到原样了
                tmp = self._root() / "temp" / f"edit_{rec['id']}{path.suffix}"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, tmp)
                result = writers.edit_office(tmp, parsed)
                data = tmp.read_bytes()
                tmp.unlink(missing_ok=True)
                new = self.store.add_version(rec["id"], data=data, note="模型就地改写")
                echo = await readers.read(Path(new["path"]), limit=300)
                return f"{result}；已存成第 {new['current_version']} 版。回读确认：{echo[:300]}"
            return "没有给内容或 ops，什么都没改。"
        except Exception as exc:
            return f"改写失败（{type(exc).__name__}: {exc}）"

    @filter.llm_tool(name="file_new")
    async def file_new(
        self,
        event: AstrMessageEvent,
        name: str,
        content: str = "",
        from_id: str = "",
    ):
        """新建文件。用户要你写文档/整理清单时用 content；要「照这份改一份」时用 from_id 复制原文件再改。

        Args:
            name(string): 文件名，必须带扩展名，如 周报.docx、数据.xlsx、汇报.pptx、清单.md
            content(string): 文件内容。xlsx 传 {"sheets":[{"name":"Sheet1","rows":[["列1","列2"],[1,2]]}]}；pptx 传 {"slides":[{"title":"页标题","bullets":["第一条"]}]}；docx 传 {"title":"标题","paragraphs":["第一段"]}；文本类直接传正文
            from_id(string): 复制哪个已有文件（id 或名字），留空表示不复制
        """
        try:
            if from_id:
                src = self._resolve(from_id)
                if not src:
                    return f"没找到要复制的文件：{from_id}"
                rec = self.store.duplicate(
                    src["id"],
                    name=name or src["name"],
                    session=event.unified_msg_origin,
                    note=f"复制自 {src['name']} v{src['current_version']}",
                )
                return (
                    f"已复制成新文件 {rec['name']}（id={rec['id']}，"
                    f"第 {rec['current_version']} 版）；接着用 file_write 改它，版式与格式保持原样"
                )
            suffix = Path(name).suffix.lower()
            if suffix in (".xlsx", ".pptx", ".docx"):
                data = writers.build_office(name, content or "")
            elif suffix in (".doc", ".xls", ".ppt"):
                return "旧版 Office 格式存不进去，请用 .docx/.xlsx/.pptx。"
            else:
                data = (content or "").encode("utf-8")
            rec = self.store.add(
                name=name,
                session=event.unified_msg_origin,
                data=data,
                sender=event.get_sender_name() or "",
                note="模型生成",
            )
            return f"已生成 {rec['name']}（id={rec['id']}，{human_size(rec['size'])}）"
        except Exception as exc:
            return f"生成失败（{type(exc).__name__}: {exc}）"

    @filter.llm_tool(name="file_send")
    async def file_send(self, event: AstrMessageEvent, file_id: str, version: int = 0):
        """把文件读写小助手里的文件发到当前聊天。用户说「发给我」「传过来」时调用。

        Args:
            file_id(string): 文件 id 或文件名关键词
            version(number): 指定版本号，0 表示最新版
        """
        rec = self._resolve(file_id)
        if not rec:
            return f"没找到文件：{file_id}"
        path = self._path_of(rec, version)
        if version:
            target = self.store.temp_dir / f"{rec['id']}_v{version}{rec['ext']}"
            writers.copy_for(path, target)
            path = target
        return await send_file(event, path, rec["name"])

    @filter.llm_tool(name="file_pdf")
    async def file_pdf(
        self,
        event: AstrMessageEvent,
        file_id: str,
        action: str = "pages",
        pages: str = "",
    ):
        """处理 PDF。keep=只保留指定页并存成新版本；pages=把页渲染成图，用来看版式或读扫描件。

        Args:
            file_id(string): 文件 id 或文件名关键词
            action(string): keep / pages
            pages(string): keep 用，如 "1-3,5"
        """
        rec = self._resolve(file_id)
        if not rec or rec["kind"] != "pdf":
            return f"没找到 PDF：{file_id}"
        path = self._path_of(rec)
        action = (action or "pages").strip().lower()
        try:
            if action == "keep":
                wanted = _parse_pages(pages)
                if not wanted:
                    return "页码格式不对，示例：1-3,5"
                out = self.store.temp_dir / f"{rec['id']}_keep.pdf"
                msg = writers.pdf_keep_pages(path, out, wanted)
                new = self.store.add_version(rec["id"], data=out.read_bytes(), note="保留指定页")
                out.unlink(missing_ok=True)
                return f"{msg}；已存成第 {new['current_version']} 版"
            shots = readers.pdf_page_images(path, 6)
            if not shots:
                return "按页渲染失败（缺 pypdfium2 或 PDF 损坏）。"
            desc = await self.vision.describe(shots)
            return f"《{rec['name']}》前 {len(shots)} 页看图结果：\n{desc}"
        except Exception as exc:
            return f"处理失败（{type(exc).__name__}: {exc}）"

    @filter.llm_tool(name="file_video_link")
    async def file_video_link(self, event: AstrMessageEvent, url: str, keep: bool = False):
        """用户发来视频链接（B站/YouTube 等）问讲了什么时调用：临时下载、抽帧看懂，看完默认删掉。

        Args:
            url(string): 视频链接
            keep(bool): true 表示顺便存进文件读写小助手，false 表示看完就删
        """
        if not self.config.get("video_link_enabled", False):
            return "视频链接解析已关闭。"
        if not url.lower().startswith(("http://", "https://")):
            return "这不是一个链接。"
        path, title = links.fetch(
            url,
            self.store.temp_dir / "links",
            cookies=str(self.config.get("video_link_cookies") or ""),
            max_mb=int(self.config.get("max_video_mb") or 2048),
        )
        if not path:
            return f"视频下载失败：{title}"
        try:
            desc = await self._describe_video(path, title or "视频")
            if not keep:
                return desc
            rec = self.store.add(
                name=f"{title or 'video'}{path.suffix}",
                session=event.unified_msg_origin,
                src=path,
                sender=event.get_sender_name() or "",
                note="视频链接",
            )
            return f"{desc}\n已存进文件读写小助手：{rec['name']}（id={rec['id']}）"
        finally:
            if keep and self.config.get("video_link_auto_delete", True):
                path.unlink(missing_ok=True)
            elif not keep:
                path.unlink(missing_ok=True)

    # ── 内部工具方法 ─────────────────────────────────────────
    async def _describe_video(self, path: Path, title: str) -> str:
        count = max(1, min(int(self.config.get("video_frames") or 8), 12))
        frames = video_frames(path, self.store.temp_dir / "frames" / path.stem, count)
        if not frames:
            return "视频抽帧失败（ffmpeg 不可用或文件损坏）。"
        desc = await self.vision.describe(frames)
        return f"《{title}》按帧看内容（抽 {len(frames)} 帧）：\n{desc}"

    def _resolve(self, key: str) -> dict[str, Any] | None:
        key = (key or "").strip()
        if not key:
            return None
        rec = self.store.get(key)
        if rec:
            return rec
        hits = self.store.search(query=key, limit=2)
        return hits[0] if hits else None

    def _path_of(self, rec: dict[str, Any], version: int = 0) -> Path:
        if version and int(version) != int(rec["current_version"]):
            for v in self.store.versions(rec["id"]):
                if int(v["version"]) == int(version):
                    return Path(v["path"])
        return Path(rec.get("path") or "")

    # ── Web API ─────────────────────────────────────────────
    def _register_web_api(self) -> None:
        routes = [
            ("/list", self._api_list, ["GET"]),
            ("/detail/{file_id}", self._api_detail, ["GET"]),
            ("/content/{file_id}", self._api_content, ["GET"]),
            ("/keyfile/{file_id}", self._api_keyfile, ["GET"]),
            ("/save", self._api_save, ["POST"]),
            ("/delete", self._api_delete, ["POST"]),
            ("/rollback", self._api_rollback, ["POST"]),
            ("/send", self._api_send, ["POST"]),
            ("/upload", self._api_upload, ["POST"]),
        ]
        for route, handler, methods in routes:
            try:
                self.context.register_web_api(
                    f"/{PLUGIN_NAME}{route}", handler, methods, f"文件读写小助手 {route}"
                )
            except Exception as exc:
                logger.warning(f"[文件读写小助手] 注册接口 {route} 失败：{exc}")

    async def _api_list(self, **_: Any):
        kind = (web_request.query.get("kind") or "").strip()
        keyword = (web_request.query.get("q") or "").strip()
        items = self.store.search(kind=kind or None, query=keyword)
        counts = self.store.counts()
        fallback = ""
        if kind and not items and any(counts.values()):
            # 选中的类型是空的但库里明明有文件：退回全部，别让人以为文件丢了
            items = self.store.search(query=keyword)
            fallback = kind
        return json_response(
            {
                "items": items,
                "counts": counts,
                "stats": self.store.stats(),
                "labels": KIND_LABELS,
                "all": fallback,
            }
        )

    async def _api_detail(self, file_id: str = "", **_):
        rec = self.store.get(file_id)
        if not rec:
            return json_response({"error": "not found"}, status_code=404)
        return json_response({"file": rec, "versions": self.store.versions(file_id)})

    async def _api_content(self, file_id: str = "", **_):
        rec = self.store.get(file_id)
        if not rec:
            return json_response({"error": "not found"}, status_code=404)
        path = self._path_of(rec)
        text = await readers.read(path, ocr=False, limit=200000)
        return json_response({"text": text, "editable": writers.is_textual(path)})

    async def _api_keyfile(self, file_id: str = "", **_):
        rec = self.store.get(file_id)
        if not rec:
            return json_response({"error": "not found"}, status_code=404)
        return file_response(self._path_of(rec), filename=rec["name"])

    async def _api_save(self, **_):
        body = await web_request.json(default={}) or {}
        rec = self.store.get(str(body.get("file_id") or ""))
        if not rec:
            return json_response({"error": "not found"}, status_code=404)
        content = str(body.get("content") or "")
        if not writers.is_textual(self._path_of(rec)):
            return json_response(
                {"error": "二进制文件不能在线编辑，请用 file_new 生成新版本"},
                status_code=400,
            )
        new = self.store.add_version(rec["id"], data=content.encode("utf-8"), note="面板编辑")
        return json_response({"ok": True, "file": new})

    async def _api_delete(self, **_):
        body = await web_request.json(default={}) or {}
        ok = self.store.delete(str(body.get("file_id") or ""))
        return json_response({"ok": ok})

    async def _api_rollback(self, **_):
        body = await web_request.json(default={}) or {}
        fid = str(body.get("file_id") or "")
        ver = int(body.get("version") or 0)
        rec = self.store.get(fid)
        if not rec or not ver:
            return json_response({"error": "bad request"}, status_code=400)
        src = self._path_of(rec, ver)
        if not src.exists():
            return json_response({"error": "版本文件丢失"}, status_code=404)
        new = self.store.add_version(fid, data=src.read_bytes(), note=f"回滚自 v{ver}")
        return json_response({"ok": True, "file": new})

    async def _api_send(self, **_):
        body = await web_request.json(default={}) or {}
        rec = self.store.get(str(body.get("file_id") or ""))
        umo = str(body.get("umo") or "").strip()
        if not rec or not umo:
            return json_response({"error": "需要 file_id 与 umo"}, status_code=400)
        try:
            from astrbot.api.event import MessageChain

            chain = MessageChain(chain=[FileComp(name=rec["name"], file=str(self._path_of(rec)))])
            ok = await self.context.send_message(umo, chain)
            return json_response({"ok": bool(ok)})
        except Exception as exc:
            return json_response({"error": str(exc)}, status_code=500)

    async def _api_upload(self, **_):
        """一次性 base64 上传，或 upload_id + chunk_b64 分片续传（最后一片带 last=true）。"""
        import base64 as _b64

        body = await web_request.json(default={}) or {}
        name = str(body.get("name") or "")
        session = str(body.get("session") or "面板上传")
        try:
            if body.get("upload_id"):
                rec = self.store.upload_part(
                    str(body["upload_id"]),
                    _b64.b64decode(str(body.get("chunk_b64") or "")),
                    bool(body.get("last")),
                    name=name,
                    session=session,
                    note="面板上传",
                )
                if rec is None:
                    return json_response({"ok": True, "pending": True})
            else:
                raw = _b64.b64decode(str(body.get("content_b64") or ""))
                rec = self.store.add(name=name, session=session, data=raw, note="面板上传")
        except Exception as exc:
            return json_response({"error": f"上传失败：{exc}"}, status_code=400)
        return json_response({"ok": True, "file": rec})


def _parse_pages(text: str) -> list[int]:
    out: list[int] = []
    for part in (text or "").replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, _, hi = part.partition("-")
            if lo.strip().isdigit() and hi.strip().isdigit():
                out.extend(range(int(lo), int(hi) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out
