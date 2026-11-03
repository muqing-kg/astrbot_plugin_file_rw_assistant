"""面板前端调用的接口必须都在 main.py 里注册过，防止改动后前端 404。"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
APP = (ROOT / "views" / "file_rw_assistant" / "app.js").read_text(encoding="utf-8")


def registered():
    # routes 列表里的 ("/xxx", ...) 与 ("/xxx/{id}", ...)
    return {
        m.group(1).split("/")[1]
        for m in re.finditer(r'\("(/[^"]+)"', MAIN)
    }


def called():
    # api('/list?...')、api('/delete')、VIEW.download('download')
    names = set(re.findall(r"api\('/?([a-z_]+)", APP))
    names |= set(re.findall(r"VIEW\.download\('([a-z_]+)'", APP))
    return names


class TestRoutes(unittest.TestCase):
    def test_frontend_endpoints_registered(self):
        missing = called() - registered()
        self.assertEqual(missing, set(), f"前端调了没注册的接口：{missing}")

    def test_no_path_param_routes(self):
        # 面板桥不认路径参数路由（/detail/{id} 一律 404），只能走查询参数
        self.assertNotIn("{", "".join(re.findall(r'\("(/[^"]+)"', MAIN)))


if __name__ == "__main__":
    unittest.main()
