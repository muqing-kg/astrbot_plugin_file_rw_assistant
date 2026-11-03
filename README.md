# 文件仓（astrbot_plugin_file_vault）

聊天里的文件不再是一次性的。群里、私聊里出现的文档会安静地进仓，按会话归档、留版本历史，
模型能自己翻、自己读、自己改，改完直接发回来；面板里点开就能浏览、预览、在线改文本、回滚、下载、删。

## 收什么

Word（`.docx/.doc`）、Excel（`.xlsx/.xls`）、PPT（`.pptx/.ppt`）、PDF、文本（`.txt/.log`）、
Markdown（`.md/.markdown`）、代码（`.py/.js/.ts/.json/.yaml/.yml/.sh/.sql/.html/.css/.toml/.ini`）、
表格数据（`.csv/.tsv`）、视频（`.mp4/.mov/.mkv/.avi/.webm`）。

不收：图片、音频、安装包、压缩包。

## 模型能干什么

| 工具 | 场景 |
|---|---|
| `file_list` | 「仓里有哪些文件」 |
| `file_read` | 「这个 PDF 讲了啥」「视频里在演什么」 |
| `file_write` | 「把第三行数字改成 2024」（文本全量替换，Office 按 ops 就地改） |
| `file_new` | 「给我写个脚本 / 出个周报」 |
| `file_send` | 「发给我」 |

改 Office 时走「打开-改-保存」：Excel 只动指定单元格（列宽、公式、样式都还在），
PPT 只改已有形状的文字（母版不动），Word 只改指定段落。

## 面板

插件卡「查看页面」进入，两个标签页：

- **文件**：左侧类型栏（没有文件多的类型灰显），右侧表格，点行开抽屉——预览内容、在线改文本、版本历史回滚、下载、发到会话、删除。
- **设置**：与插件配置页读写同一份配置。

## 配置

| 项 | 默认 | 说明 |
|---|---|---|
| `retention_days` | 90 | 超过即自动删，0 为永久 |
| `max_versions` | 20 | 单文件版本上限，超了淘汰最旧 |
| `max_file_mb` / `max_video_mb` | 200 / 2048 | 单文件上限 |
| `video_frames` / `max_vision_images` | 8 / 6 | 抽帧数与单次识图张数 |
| `auto_cleanup` | 开 | 每 6 小时扫一次 |
| `storage_root` | 空 | 空=插件数据目录（随面板备份）；填绝对路径则独立存放 |
| `text_model_provider_id` / `vision_model_provider_id` | 空 | 空=跟随框架当前模型 |
| `enable_pdf_ocr` | 开 | PDF 无文字层时按图识别 |
| `video_link_enabled` 等 | — | 视频链接解析，默认解析完即删 |

## 限制（用之前先看这几条）

- **AstrBot 版本**：`>=4.16,<5`。用到插件页面与 `register_web_api`，更老的版本没有这两样。
- **直发文件依赖平台**：QQ（aiocqhttp / OneBot v11）需要 NapCat 且该会话可上传；其他平台走框架 `File` 组件，平台不支持直发时自动降级为「文件已在文件仓」提示，不报错。
- **在线编辑只对文本类**（文本 / Markdown / 代码 / CSV）。Office 与 PDF 是压缩包结构，在线改风险大于收益，只给下载与版本回滚。
- **旧版 Office（`.doc/.xls/.ppt`）** 只能入库与下载，不能解析内容——请转成新版格式。
- **PDF 改正文**会破坏版式，只提供整页保留/抽取。
- **视频**只在明确问「讲了什么」时抽帧理解（默认 8 帧），不做常驻监听；链接解析靠 `yt-dlp`，抖音等要填 cookies。
- **依赖**：`python-pptx`、`reportlab`（`requirements.txt` 自动装）；视频抽帧需要容器内有 `ffmpeg`。

## 目录结构

```
data/plugin_data/astrbot_plugin_file_vault/
├─ index.db                      元数据
├─ files/<会话>/<年-月>/<原名>.<id>.<ext>   最新版，人眼可读
├─ versions/<id>/vN.<ext>        历史版本
└─ temp/                         抽帧、导出临时物
```

## 开发

```bash
python -m unittest tests.test_store -v
```

作者：沐倾
