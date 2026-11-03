"""改写与生成。原则：能就地改就就地改，保列宽/公式/母版；改不了才重生成。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

TEXTUAL = {
    ".txt", ".log", ".md", ".markdown", ".py", ".js", ".ts", ".json", ".yaml",
    ".yml", ".sh", ".sql", ".html", ".css", ".toml", ".ini", ".csv", ".tsv",
}


def is_textual(path: Path) -> bool:
    return path.suffix.lower() in TEXTUAL


def edit_office(path: Path, ops: list[dict[str, Any]]) -> str:
    """按 ops 就地改 Office 文件，返回改了多少处。"""
    suffix = path.suffix.lower()
    done = 0
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        wb = load_workbook(str(path))
        for op in ops:
            ws = wb[op.get("sheet")] if op.get("sheet") else wb.active
            cell = str(op.get("cell") or "").strip()
            if not cell:
                continue
            ws[cell] = op.get("value")
            done += 1
        wb.save(str(path))
        return f"已改 {done} 个单元格"
    if suffix == ".pptx":
        from pptx import Presentation

        prs = Presentation(str(path))
        for op in ops:
            idx = int(op.get("slide") or 1) - 1
            if not 0 <= idx < len(prs.slides):
                continue
            texts = [
                s
                for s in prs.slides[idx].shapes
                if s.has_text_frame and s.text_frame.text.strip()
            ]
            pos = int(op.get("shape") or 1) - 1
            if 0 <= pos < len(texts):
                frame = texts[pos].text_frame
                frame.paragraphs[0].text = str(op.get("text") or "")
                for extra in frame.paragraphs[1:]:
                    extra.text = ""
                done += 1
        prs.save(str(path))
        return f"已改 {done} 处文字（母版与版式未动）"
    if suffix == ".docx":
        from docx import Document

        doc = Document(str(path))
        for op in ops:
            idx = int(op.get("paragraph") or 1) - 1
            filled = [p for p in doc.paragraphs if p.text.strip()]
            if 0 <= idx < len(filled):
                filled[idx].text = str(op.get("text") or "")
                done += 1
        doc.save(str(path))
        return f"已改 {done} 段文字"
    return f"{suffix} 不支持就地改写"


def pdf_keep_pages(src: Path, dst: Path, pages: list[int]) -> str:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(src))
    writer = PdfWriter()
    kept = []
    for p in pages:
        idx = int(p) - 1
        if 0 <= idx < len(reader.pages):
            writer.add_page(reader.pages[idx])
            kept.append(idx + 1)
    if not kept:
        return "页码无效，未生成新 PDF"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("wb") as fh:
        writer.write(fh)
    return f"已保留第 {kept} 页，共 {len(kept)} 页"


def copy_for(path: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    return target


def build_office(name: str, content: str) -> bytes:
    """按扩展名把 JSON 结构写成 Office 文件。

    .xlsx: {"sheets":[{"name":"Sheet1","rows":[["列1","列2"],[1,2]]}]}，也可直接给二维数组
    .pptx: {"slides":[{"title":"页标题","bullets":["第一条","第二条"]}]}
    .docx: {"title":"标题","paragraphs":["第一段","第二段"]}，也可直接给纯文本（按行分段）
    """
    import io
    import json

    suffix = Path(name).suffix.lower()

    def load():
        try:
            return json.loads(content)
        except Exception as exc:
            raise ValueError(f"内容不是合法 JSON（{exc}）") from exc

    buf = io.BytesIO()
    if suffix == ".xlsx":
        from openpyxl import Workbook

        data = load()
        sheets = data.get("sheets") if isinstance(data, dict) else None
        if not sheets:
            sheets = [{"name": "Sheet1", "rows": data if isinstance(data, list) else []}]
        wb = Workbook()
        wb.remove(wb.active)
        for spec in sheets:
            ws = wb.create_sheet(str(spec.get("name") or "Sheet1")[:31])
            for row in spec.get("rows") or []:
                ws.append(list(row) if isinstance(row, (list, tuple)) else [row])
        wb.save(buf)
    elif suffix == ".pptx":
        from pptx import Presentation

        data = load()
        slides = data.get("slides") if isinstance(data, dict) else [{"bullets": data}]
        if not slides:
            raise ValueError('内容需要 {"slides":[{"title":"…","bullets":["…"]}]}')
        prs = Presentation()
        for spec in slides:
            slide = prs.slides.add_slide(prs.slide_layouts[1])  # 标题 + 内容
            if slide.shapes.title is not None:
                slide.shapes.title.text = str(spec.get("title") or "")
            bullets = [str(b) for b in (spec.get("bullets") or [])] or [""]
            frame = slide.placeholders[1].text_frame
            frame.text = bullets[0]
            for extra in bullets[1:]:
                frame.add_paragraph().text = extra
        prs.save(buf)
    elif suffix == ".docx":
        from docx import Document

        doc = Document()
        try:
            data = load()
        except ValueError:
            data = None
        if isinstance(data, dict):
            if data.get("title"):
                doc.add_heading(str(data["title"]), level=1)
            for para in data.get("paragraphs") or []:
                doc.add_paragraph(str(para))
        else:
            for line in (content or "").splitlines():
                doc.add_paragraph(line)
        doc.save(buf)
    else:
        raise ValueError(f"{suffix or name} 不是 Office 格式")
    return buf.getvalue()
