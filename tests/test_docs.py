"""文档不能落后于代码：版本号必须在更新日志里，README 不能写已删掉的功能。"""

import json
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

    def test_i18n_matches_metadata(self):
        # 面板卡片显示的是 i18n 里的 metadata 段，和 metadata.yaml 不一致就会出现「描述没改」
        i18n = json.loads(
            (ROOT / ".astrbot-plugin" / "i18n" / "zh-CN.json").read_text(encoding="utf-8")
        )["metadata"]
        yaml_desc = re.search(r"^desc:\s*(.+)$", META, re.M).group(1).strip()
        yaml_name = re.search(r"^display_name:\s*(.+)$", META, re.M).group(1).strip()
        self.assertEqual(i18n["desc"], yaml_desc, "i18n 的 desc 与 metadata.yaml 不一致")
        self.assertEqual(i18n["display_name"], yaml_name, "i18n 的 display_name 与 metadata.yaml 不一致")


if __name__ == "__main__":
    unittest.main()
