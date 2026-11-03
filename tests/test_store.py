"""最小自检：python -m unittest tests.test_store（不需要 AstrBot 框架）。"""

import asyncio
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import readers, writers  # noqa: E402
from core.store import FileStore, kind_of  # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="fv_"))
        self.store = FileStore(self.root, retention_days=90, max_versions=3)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_kind_of(self):
        assert kind_of("周报.docx") == "word"
        assert kind_of("a.PDF") == "pdf"
        assert kind_of("x.zip") is None

    def test_add_and_version(self):
        rec = self.store.add(name="笔记.md", session="QQ-群:1", data="第一版".encode())
        assert rec["current_version"] == 1 and rec["kind"] == "markdown"
        assert Path(rec["path"]).read_text(encoding="utf-8") == "第一版"

        rec = self.store.add_version(rec["id"], data="第二版".encode())
        assert rec["current_version"] == 2
        assert Path(rec["path"]).read_text(encoding="utf-8") == "第二版"
        versions = self.store.versions(rec["id"])
        assert [v["version"] for v in versions] == [2, 1]
        old = [v for v in versions if v["version"] == 1][0]
        assert Path(old["path"]).read_text(encoding="utf-8") == "第一版"  # 旧版被归档

    def test_version_cap(self):
        rec = self.store.add(name="a.txt", session="s", data=b"1")
        for i in range(2, 7):
            rec = self.store.add_version(rec["id"], data=str(i).encode())
        left = [v["version"] for v in self.store.versions(rec["id"])]
        assert left == [6, 5, 4], left

    def test_delete_removes_disk(self):
        rec = self.store.add(name="b.txt", session="s", data=b"x")
        path = Path(rec["path"])
        assert self.store.delete(rec["id"]) is True
        assert not path.exists()
        assert self.store.get(rec["id"]) is None

    def test_search_and_counts(self):
        self.store.add(name="报表.xlsx", session="s", data=b"x")
        self.store.add(name="说明.txt", session="s", data=b"y")
        assert [r["name"] for r in self.store.search(kind="excel")] == ["报表.xlsx"]
        assert self.store.counts()["excel"] == 1
        assert self.store.search(query="说明")[0]["name"] == "说明.txt"

    def test_upload_part_chunks(self):
        assert self.store.upload_part("u1", b"ab", False, name="q.txt", session="s") is None
        rec = self.store.upload_part("u1", b"cd", True, name="q.txt", session="s")
        assert rec["size"] == 4
        assert Path(rec["path"]).read_bytes() == b"abcd"
        assert not list(self.store.temp_dir.glob("up_*.part"))  # 临时片已清

    def test_duplicate_keeps_content(self):
        rec = self.store.add(name="模板.pptx", session="s", data=b"PK\x03\x04data")
        copy = self.store.duplicate(rec["id"], name="模板-改.pptx", session="s2")
        assert copy["id"] != rec["id"] and copy["session"] == "s2"
        assert Path(copy["path"]).read_bytes() == b"PK\x03\x04data"
        assert copy["current_version"] == 1

    def test_search_filters(self):
        a = self.store.add(name="甲.txt", session="QQ:1", sender="阿珂", data=b"a")
        self.store.add(name="乙.txt", session="QQ:2", sender="小满", data=b"b")
        assert [r["name"] for r in self.store.search(sender="阿珂")] == ["甲.txt"]
        assert [r["name"] for r in self.store.search(session="QQ:2")] == ["乙.txt"]
        assert len(self.store.search(days=1)) == 2
        # 时间戳往前挪一天，days=1 就该筛掉
        with self.store._conn() as conn:
            conn.execute("UPDATE files SET updated_at='2000-01-01 00:00:00' WHERE id=?", (a["id"],))
        assert [r["name"] for r in self.store.search(days=1)] == ["乙.txt"]

    def test_read_slice(self):
        f = self.root / "long.txt"
        f.write_text("\n".join(f"第{i}行 内容" for i in range(1, 301)), encoding="utf-8")
        part = asyncio.run(readers.read(f, lines="100-102"))
        assert "第100行" in part and "第102行" in part and "第103行" not in part
        hit = asyncio.run(readers.read(f, find="第250行"))
        assert "250: 第250行" in hit and "第251行" not in hit
        assert "没找到" in asyncio.run(readers.read(f, find="不存在的词"))

    @unittest.skipUnless(importlib.util.find_spec("openpyxl"), "缺 openpyxl")
    def test_build_xlsx_roundtrip(self):
        data = writers.build_office(
            "成绩.xlsx", '{"sheets":[{"name":"表1","rows":[["姓名","分数"],["阿珂",90]]}]}'
        )
        p = self.root / "成绩.xlsx"
        p.write_bytes(data)
        text = asyncio.run(readers.read(p))
        assert "姓名 | 分数" in text and "阿珂 | 90" in text, text

    @unittest.skipUnless(importlib.util.find_spec("docx"), "缺 python-docx")
    def test_build_docx_roundtrip(self):
        data = writers.build_office(
            "周报.docx", '{"title":"周报","paragraphs":["本周完成三件事","下周继续"]}'
        )
        p = self.root / "周报.docx"
        p.write_bytes(data)
        text = asyncio.run(readers.read(p))
        assert "本周完成三件事" in text and "下周继续" in text, text

    @unittest.skipUnless(importlib.util.find_spec("pptx"), "缺 python-pptx")
    def test_build_pptx_roundtrip(self):
        data = writers.build_office(
            "汇报.pptx", '{"slides":[{"title":"本月成绩","bullets":["收入涨两成","成本降一成"]}]}'
        )
        p = self.root / "汇报.pptx"
        p.write_bytes(data)
        text = asyncio.run(readers.read(p))
        assert "本月成绩" in text and "收入涨两成" in text, text

    def test_readers_text_and_csv(self):
        txt = self.root / "x.txt"
        txt.write_text("你好\n世界", encoding="utf-8")
        assert "你好" in asyncio.run(readers.read(txt))
        csvf = self.root / "t.csv"
        csvf.write_text("a,b\n1,2\n", encoding="utf-8")
        assert "a | b" in asyncio.run(readers.read(csvf))


if __name__ == "__main__":
    unittest.main(verbosity=2)
