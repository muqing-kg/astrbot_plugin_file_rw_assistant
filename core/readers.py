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


def _parse_range(text: str, total: int) -> tuple[int, int]:
    """把 "30" / "30-32" 解析成 1 起的闭区间，越界自动夹紧。"""
    text = (text or "").replace("，", "-").replace("~", "-").strip()
    if not text:
        return 1, max(total, 1)
    lo, _, hi = text.partition("-")
    try:
        start = int(lo) if lo.strip() else 1
        end = int(hi) if hi.strip() else (start if "-" not in text else total)
    except ValueError:
        return 1, total
    start = max(1, min(start, total or 1))
    end = max(start, min(end, total or start))
    return start, end


def _pdf(path: Path, pages: str = "") -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    total = len(reader.pages)
    if pages:
        start, end = _parse_range(pages, total)
        wanted = range(start, end + 1)
        out = [f"[PDF 共 {total} 页，本次看第 {start}-{end} 页]"]
    else:
        wanted = range(1, min(total, 60) + 1)
        out = [f"[PDF 共 {total} 页]"]
    for idx in wanted:
        text = (reader.pages[idx - 1].extract_text() or "").strip()
        if text:
            out.append(f"[第{idx}页]\n{text}")
    return "\n".join(out)


def _find(text: str, keyword: str, limit: int = 40) -> str:
    """按行找关键词，只回命中行（带行号），省上下文。"""
    key = keyword.strip().lower()
    hits = [
        f"{i}: {line.strip()}"
        for i, line in enumerate(text.splitlines(), 1)
        if key in line.lower()
    ]
    if not hits:
        return f"没找到「{keyword}」。"
    head = "\n".join(hits[:limit])
    if len(hits) > limit:
        head += f"\n…共 {len(hits)} 行命中，已显示前 {limit} 行"
    return head


def _lines(text: str, spec: str) -> str:
    rows = text.splitlines()
    start, end = _parse_range(spec, len(rows))
    body = "\n".join(rows[start - 1:end])
    return f"[第 {start}-{end} 行，共 {len(rows)} 行]\n{body}"


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
                        info = zf.getinfo(name)
                        if info.file_size > 8 * 1024 * 1024:  # 单张超 8MB 不送模型
                            continue
                        shots.append(zf.read(name))
                        if len(shots) >= limit:
                            break
        except Exception:
            return shots
    return shots


async def read(
    path: Path,
    *,
    ocr: bool = False,
    vision=None,
    limit: int = MAX_CHARS,
    pages: str = "",
    lines: str = "",
    find: str = "",
) -> str:
    """返回文本摘要。

    pages 只对 PDF 生效（"30" / "30-32"）；lines 按行区间取（"100-200"）；
    find 只回关键词命中的行。三者都需要先拿到全文，所以会临时放宽截断。
    ocr=True 且 PDF 没有文字层时，整页渲染交给视觉模型。
    """
    suffix = path.suffix.lower()
    slicing = bool(lines or find)
    cap = 200_000 if slicing else limit
    try:
        if suffix in (".csv", ".tsv"):
            text = _csv(path)
        elif suffix in (".txt", ".log", ".md", ".markdown", ".py", ".js", ".ts",
                        ".json", ".yaml", ".yml", ".sh", ".sql", ".html", ".css",
                        ".toml", ".ini"):
            text = _text(path)
        elif suffix == ".docx":
            text = _docx(path)
        elif suffix == ".xlsx":
            text = _xlsx(path)
        elif suffix == ".pptx":
            text = _pptx(path)
        elif suffix == ".pdf":
            text = _pdf(path, pages)
            if ocr and len(text) < 50 and vision is not None:
                shots = pdf_page_images(path, 6)
                if not shots:
                    return _clip("（PDF 无文字层，服务器缺 pypdfium2，无法按页识图）\n" + text, limit)
                return _clip("（PDF 无文字层，按页渲染识图）\n" + await vision.describe(shots), limit)
            return _clip(_find(text, find) if find else (_lines(text, lines) if lines else text), limit)
        elif suffix in (".doc", ".xls", ".ppt"):
            return "旧版 Office 格式（.doc/.xls/.ppt）不支持直接解析，请转成新版格式。"
        else:
            return f"不支持的类型：{suffix}"
    except Exception as exc:  # 解析失败要说清楚，不吞
        return f"解析失败（{type(exc).__name__}: {exc}）"
    if find:
        return _find(text, find)
    if lines:
        return _lines(text, lines)
    return _clip(text, cap)
