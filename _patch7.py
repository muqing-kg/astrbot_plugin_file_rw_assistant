import pathlib
import re

root = pathlib.Path(".")

# ── 1) vlm.py：占位符替换 + describe 里填 count ──
vp = root / "core" / "vlm.py"
v = vp.read_text(encoding="utf-8")
v = v.replace(
    "import base64\nimport math",
    "import base64\nimport math\nimport re",
    1,
)
v = v.replace(
    'def _data_uri(data: bytes, mime: str = "image/png") -> str:',
    'def fill(template: str, **values: object) -> str:\n'
    '    """把模板里的 {name} 换成给定值；不认识的花括号原样留着，别让它报错。"""\n'
    '    if not template:\n'
    '        return ""\n'
    '\n'
    '    def sub(m: "re.Match[str]") -> str:\n'
    '        key = m.group(1)\n'
    '        return str(values[key]) if key in values else m.group(0)\n'
    '\n'
    '    return re.sub(r"\\{(\\w+)\\}", sub, template)\n'
    '\n'
    '\n'
    'def _data_uri(data: bytes, mime: str = "image/png") -> str:',
    1,
)
v = v.replace(
    '        resp = await provider.text_chat(\n'
    '            prompt=(prompt or self.default_prompt or PROMPT),',
    '        resp = await provider.text_chat(\n'
    '            prompt=fill(prompt or self.default_prompt or PROMPT, count=len(images)),',
    1,
)
vp.write_text(v, encoding="utf-8")

# ── 2) main.py：视频与摘要提示词填变量；旧插件名补注册路由 ──
p = root / "main.py"
s = p.read_text(encoding="utf-8")
s = s.replace(
    "from .core.vlm import Vision, duration_of, extract_audio, frames_for, subtitle_text",
    "from .core.vlm import (\n    Vision,\n    duration_of,\n    extract_audio,\n    fill,\n    frames_for,\n    subtitle_text,\n)",
    1,
)
s = s.replace(
    '        desc = await self.vision.describe(\n'
    '            frames, prompt=str(self.cfg.get("video_prompt") or ""), audio=audio\n'
    '        )',
    '        prompt = fill(\n'
    '            str(self.cfg.get("video_prompt") or ""),\n'
    '            title=title,\n'
    '            seconds=f"{seconds:.0f}",\n'
    '            frames=len(frames),\n'
    '            audio="有" if audio else "无",\n'
    '        )\n'
    '        desc = await self.vision.describe(frames, prompt=prompt, audio=audio)',
    1,
)
s = s.replace(
    '            instruction = str(self.cfg.get("summary_prompt") or "").strip() or (',
    '            instruction = fill(\n'
    '                str(self.cfg.get("summary_prompt") or "").strip(), chars=len(text)\n'
    '            ) or (',
    1,
)
s = s.replace(
    """        for route, handler, methods in routes:
            try:
                self.context.register_web_api(
                    f"/{PLUGIN_NAME}{route}", handler, methods, f"文件读写小助手 {route}"
                )
            except Exception as exc:
                logger.warning(f"[文件读写小助手] 注册接口 {route} 失败：{exc}")""",
    """        # 浏览器里缓存的旧页面仍在用旧插件名调接口，旧名一并注册，别让列表白白空着
        prefixes = [PLUGIN_NAME, "astrbot_plugin_doc_hub", "astrbot_plugin_file_vault"]
        for prefix in prefixes:
            for route, handler, methods in routes:
                try:
                    self.context.register_web_api(
                        f"/{prefix}{route}", handler, methods, f"文件读写小助手 {route}"
                    )
                except Exception as exc:
                    logger.warning(f"[文件读写小助手] 注册接口 {prefix}{route} 失败：{exc}")""",
    1,
)
s = s.replace('"文件读写小助手", "1.3.1"', '"文件读写小助手", "1.3.2"', 1)
p.write_text(s, encoding="utf-8")

md = root / "metadata.yaml"
t = md.read_text(encoding="utf-8")
t = re.sub(r"(?m)^version: .*$", "version: 1.3.2", t, count=1)
md.write_text(t, encoding="utf-8")

# ── 3) index.html 资源版本号 ──
ix = root / "views" / "file_rw_assistant" / "index.html"
h = ix.read_text(encoding="utf-8")
h = h.replace("styles.css?v=1.2.3", "styles.css?v=1.3.2").replace("app.js?v=1.2.3", "app.js?v=1.3.2")
ix.write_text(h, encoding="utf-8")

# ── 4) schema：三处提示词的 hint 写清可用占位符 ──
sc = root / "_conf_schema.json"
j = sc.read_text(encoding="utf-8")
j = j.replace(
    '"留空则用这段默认文本"',
    '"留空则用这段默认文本；可用占位符 {title} {seconds} {frames} {audio}"',
    1,
)
j = j.replace(
    '"文档插图、扫描件整页渲染都走这段"',
    '"文档插图、扫描件整页渲染都走这段；可用占位符 {count}"',
    1,
)
j = j.replace(
    '"正文超过 6000 字且配了文本模型时用它压缩"',
    '"正文超过 6000 字且配了文本模型时用它压缩；可用占位符 {chars}"',
    1,
)
sc.write_text(j, encoding="utf-8")

# ── 5) 测试：fill 的容错 ──
tp = root / "tests" / "test_store.py"
tt = tp.read_text(encoding="utf-8")
add = '''
    def test_fill_keeps_unknown_braces(self):
        """占位符只换认识的键，别的花括号原样留着，不能抛异常。"""
        assert vlm.fill("时长{seconds}秒，抽{frames}帧", seconds="16", frames=8) == "时长16秒，抽8帧"
        assert vlm.fill("JSON {\\"a\\":1} 与 {nope}", nope="?") == 'JSON {"a":1} 与 ?'
        assert vlm.fill("", count=1) == ""
'''
tt = tt.replace('\n\nif __name__ == "__main__":', add + '\n\nif __name__ == "__main__":', 1)
tp.write_text(tt, encoding="utf-8")
print("v1.3.2 patched")
