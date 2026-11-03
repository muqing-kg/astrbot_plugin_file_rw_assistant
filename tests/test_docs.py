"""文档不能落后于代码：版本号必须在更新日志里，README 不能写已删掉的功能。"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def current_version():
    return re.search(r"^version:\s*(\S+)", META, re.M).group(1)


class TestDocs(unittest.TestCase):
    def test_changelog_has_current_version(self):
        ver = current_version()
        self.assertIn(f"## v{ver}", CHANGELOG, f"CHANGELOG 缺少 v{ver} 的条目")

    def test_readme_has_no_removed_features(self):
        # 侧边抽屉、在线编辑、版本回滚、发到会话都已在 v1.6.0 移除
        for word in ("详情抽屉", "在线编辑", "版本回滚", "发送到会话"):
            self.assertNotIn(word, README, f"README 还在写已移除的功能：{word}")


if __name__ == "__main__":
    unittest.main()
