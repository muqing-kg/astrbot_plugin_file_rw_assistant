"""把各类文件变成模型能吃的文本。解析失败不抛，返回可读的失败原因。"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Iterable

MAX_CHARS = 8000


def _text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _clip(text: str, limit: int = MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，原文 {len(text)} 字）"


def _csv(path: Path) -> str:
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    rows = list(csv.reader(io.StringIO(_text(path)), delimiter=delim))
    if not rows:
        return "（空表）"
    head, body = rows[0], rows[1:]
    out = [" | ".join(head)]
    for row in body[:200]:
        out.append(" | ".join(row))
    if len(body) > 200:
        out.append(f"…（共 {len(body)} 行，已显示前 200 行）")
    return "\n".join(out)


def _docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for idx, table in enumerate(doc.tables, 1):
        parts.append(f"[表格{idx}]")
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def _xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"[工作表] {ws.title}")
        for row in ws.iter_rows(max_row=200, values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(cells):
                out.append(" | ".join(cells))
    wb.close()
    return "\n".join(out)


def _pptx(path: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(path))
    out = []
    for idx, slide in enumerate(prs.slides, 1):
        out.append(f"[第{idx}页]")
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                out.append(shape.text_frame.text.strip())
    return "\n".join(out)


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    out = [f"[PDF 共 {len(reader.pages)} 页]"]
    for idx, page in enumerate(reader.pages[:60], 1):
        text = (page.extract_text() or "").strip()
        if text:
            out.append(f"[第{idx}页]\n{text}")
    return "\n".join(out)


def pdf_page_images(path: Path, limit: int = 6, dpi: int = 140) -> list[bytes]:
    """整页渲染成 PNG，交给视觉模型看版式与扫描件。缺库返回空列表。"""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return []
    shots: list[bytes] = []
    try:
        doc = pdfium.PdfDocument(str(path))
        for i in range(min(len(doc), max(limit, 1))):
            pil = doc[i].render(scale=dpi / 72).to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            shots.append(buf.getvalue())
        doc.close()
    except Exception:
        return shots
    return shots


def embedded_images(path: Path, limit: int) -> list[bytes]:
    """Office/PDF 里夹带的图片，供视觉模型认字识图。"""
    suffix = path.suffix.lower()
    shots: list[bytes] = []
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader

            for page in PdfReader(str(path)).pages[: max(limit, 1)]:
                for img in page.images:
                    shots.append(img.data)
                    if len(shots) >= limit:
                        return shots
        except Exception:
            return shots
        return shots
    if suffix in (".docx", ".xlsx", ".pptx"):
        try:
            with zipfile.ZipFile(path) as zf:
                names: Iterable[str] = [
                    n for n in zf.namelist() if n.startswith(("word/media/", "xl/media/", "ppt/media/"))
                ]
                for name in sorted(names):
                    if Path(name).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                        shots.append(zf.read(name))
                        if len(shots) >= limit:
                            break
        except Exception:
            return shots
    return shots


async def read(
    path: Path, *, ocr: bool = False, vision=None, limit: int = MAX_CHARS
) -> str:
    """返回文本摘要。ocr=True 且 PDF 没有文字层时，整页渲染交给视觉模型。"""
    suffix = path.suffix.lower()
    try:
        if suffix in (".csv", ".tsv"):
            return _clip(_csv(path), limit)
        if suffix in (".txt", ".log", ".md", ".markdown", ".py", ".js", ".ts",
                      ".json", ".yaml", ".yml", ".sh", ".sql", ".html", ".css",
                      ".toml", ".ini"):
            return _clip(_text(path), limit)
        if suffix == ".docx":
            return _clip(_docx(path), limit)
        if suffix == ".xlsx":
            return _clip(_xlsx(path), limit)
        if suffix == ".pptx":
            return _clip(_pptx(path), limit)
        if suffix == ".pdf":
            text = _pdf(path)
            if ocr and len(text) < 50 and vision is not None:
                shots = pdf_page_images(path, 6)
                if not shots:
                    return _clip("（PDF 无文字层，服务器缺 pypdfium2，无法按页识图）\n" + text, limit)
                return _clip("（PDF 无文字层，按页渲染识图）\n" + await vision.describe(shots), limit)
            return _clip(text, limit)
        if suffix in (".doc", ".xls", ".ppt"):
            return "旧版 Office 格式（.doc/.xls/.ppt）不支持直接解析，请转成新版格式。"
    except Exception as exc:  # 解析失败要说清楚，不吞
        return f"解析失败（{type(exc).__name__}: {exc}）"
    return f"不支持的类型：{suffix}"
