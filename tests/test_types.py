"""九类文件端到端自检：造真文件 → 入库 → 列表筛选 → 读 → 改 → 另存。

跑法：.venv\\Scripts\\python.exe -m unittest tests.test_types -v
缺库的格式会跳过对应断言，不假绿。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core import readers, writers
from core.store import FileStore, kind_of


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def make_pdf(path: Path) -> None:
    """手搓一个带 xref 的合法 PDF，pypdf 才能解出文字。"""
    content = b"BT /F1 16 Tf 20 50 Td (Hello PDF 4471) Tj ET"
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]"
        b"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>",
        b"<</Length " + str(len(content)).encode() + b">>stream\n" + content + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<</Size " + str(len(objs) + 1).encode() + b"/Root 1 0 R>>\nstartxref\n"
        + str(xref_at).encode() + b"\n%%EOF\n"
    )
    path.write_bytes(bytes(out))


def make_docx(path: Path) -> None:
    from docx import Document

    doc = Document()
    doc.add_paragraph("第一段：季度目标 4471")
    doc.add_paragraph("第二段：预算 120 万")
    doc.save(path)


def make_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws["A1"], ws["B1"] = "项目", "金额"
    ws["A2"], ws["B2"] = "印刷", 1200
    wb.save(path)


def make_pptx(path: Path) -> None:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "季度汇报"
    slide.placeholders[1].text = "要点一：增长 30%"
    prs.save(path)


class TypeSweep(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fv-types-"))
        self.store = FileStore(self.tmp)
        self.samples: list[Path] = []
        for name, text in [
            ("note.txt", "纯文本 4471"),
            ("readme.md", "# 标题\n正文 4471"),
            ("script.py", "print('4471')\n"),
            ("data.csv", "名称,数量\n表格,4471\n"),
            ("data.tsv", "名称\t数量\n表格\t4471\n"),
            ("app.json", '{"code": "4471"}'),
            ("old.log", "日志 4471\n"),
            ("legacy.doc", "不是真的 doc"),
            ("legacy.xls", "不是真的 xls"),
            ("legacy.ppt", "不是真的 ppt"),
        ]:
            p = self.tmp / name
            p.write_text(text, encoding="utf-8")
            self.samples.append(p)
        self.samples.append(self._make("report.pdf", make_pdf))
        if _has("docx"):
            self.samples.append(self._make("report.docx", make_docx))
        if _has("openpyxl"):
            self.samples.append(self._make("sheet.xlsx", make_xlsx))
        if _has("pptx"):
            self.samples.append(self._make("deck.pptx", make_pptx))

    def _make(self, name: str, builder) -> Path:
        p = self.tmp / name
        builder(p)
        return p

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_types_ingest_and_kind(self) -> None:
        expect = {
            ".txt": "text", ".md": "markdown", ".py": "code", ".json": "code",
            ".log": "text", ".csv": "csv", ".tsv": "csv", ".pdf": "pdf",
            ".docx": "word", ".xlsx": "excel", ".pptx": "ppt",
            ".doc": "word", ".xls": "excel", ".ppt": "ppt",
        }
        for p in self.samples:
            kind = kind_of(p.name)
            self.assertEqual(kind, expect[p.suffix], f"{p.name} 类型判断错")
            rec = self.store.add(name=p.name, session="测试会话", src=p, sender="张三")
            self.assertEqual(rec["kind"], kind)
        total = len(self.samples)
        self.assertEqual(self.store.stats()["files"], total, "入库条数不对")
        for kind in set(expect.values()):
            got = {r["name"] for r in self.store.search(kind=kind)}
            want = {p.name for p in self.samples if expect[p.suffix] == kind}
            self.assertEqual(got, want, f"按 {kind} 筛选结果不对")
        self.assertEqual(len(self.store.search(query="note")), 1)

    def test_readable_types_return_content(self) -> None:
        cases = {
            "note.txt": "4471", "readme.md": "4471", "script.py": "4471",
            "data.csv": "4471", "app.json": "4471", "old.log": "4471",
            "report.pdf": "4471",
        }
        if _has("docx"):
            cases["report.docx"] = "4471"
        if _has("openpyxl"):
            cases["sheet.xlsx"] = "1200"
        if _has("pptx"):
            cases["deck.pptx"] = "30%"
        for name, needle in cases.items():
            path = self.tmp / name
            text = asyncio.run(readers.read(path))
            self.assertIn(needle, text, f"{name} 读取内容里找不到 {needle}")

    def test_legacy_office_is_stored_but_not_parsed(self) -> None:
        for name in ("legacy.doc", "legacy.xls", "legacy.ppt"):
            text = asyncio.run(readers.read(self.tmp / name))
            self.assertIn("不支持", text, f"{name} 应给出不支持提示，实际：{text[:40]}")

    def test_edit_and_version(self) -> None:
        rec = self.store.add(name="note.txt", session="测试会话", src=self.tmp / "note.txt")
        first = self.store.add_version(rec["id"], data=b"second 4471", note="改一版")
        self.assertEqual(first["current_version"], 2)
        got = asyncio.run(readers.read(Path(first["path"])))
        self.assertIn("second", got)
        v1 = [v for v in self.store.versions(rec["id"]) if v["version"] == 1][0]
        back = self.store.add_version(rec["id"], data=Path(v1["path"]).read_bytes(), note="回滚")
        self.assertIn("纯文本", asyncio.run(readers.read(Path(back["path"]))))

    def test_office_inplace_edit(self) -> None:
        if not _has("openpyxl"):
            self.skipTest("没有 openpyxl")
        rec = self.store.add(name="sheet.xlsx", session="测试会话", src=self.tmp / "sheet.xlsx")
        before = Path(rec["path"]).read_bytes()
        work = self.tmp / "edit.xlsx"
        shutil.copy2(rec["path"], work)
        writers.edit_office(work, [{"sheet": "Sheet", "cell": "B2", "value": 9999}])
        new = self.store.add_version(rec["id"], data=work.read_bytes(), note="就地改")
        self.assertIn("9999", asyncio.run(readers.read(Path(new["path"]))))
        # 旧版本应被归档进 versions/，且仍是改之前的内容（就地改临时副本才不会污染它）
        v1 = [v for v in self.store.versions(rec["id"]) if v["version"] == 1][0]
        self.assertEqual(Path(v1["path"]).read_bytes(), before, "旧版本归档被改坏了")
        self.assertNotIn("9999", asyncio.run(readers.read(Path(v1["path"]))))

    def test_duplicate_keeps_content(self) -> None:
        rec = self.store.add(name="note.txt", session="测试会话", src=self.tmp / "note.txt")
        dup = self.store.duplicate(rec["id"], name="note-copy.txt")
        self.assertNotEqual(dup["id"], rec["id"])
        self.assertEqual(
            Path(dup["path"]).read_text(encoding="utf-8"),
            Path(rec["path"]).read_text(encoding="utf-8"),
        )

    def test_generated_office_reads_back(self) -> None:
        if not (_has("openpyxl") and _has("docx") and _has("pptx")):
            self.skipTest("缺 Office 库")
        doc = self.store.add(
            name="new.docx", session="测试会话",
            data=writers.build_office("new.docx", json.dumps({"title": "周报", "paragraphs": ["本周 4471"]}, ensure_ascii=False)),
        )
        self.assertIn("4471", asyncio.run(readers.read(Path(doc["path"]))))


if __name__ == "__main__":
    unittest.main()
