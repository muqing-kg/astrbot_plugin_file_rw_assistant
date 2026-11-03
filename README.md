# 文枢（astrbot_plugin_doc_hub）

聊天里的文件不该是一次性的。群里、私聊里出现的文档会安静地进仓，按会话归档、留版本历史；
模型能自己翻、自己读（扫描件也能看）、自己改、自己生成，改完直接发回来；面板里点开就能用。

「文枢」取文档中枢：收、存、读、改、发五件事都在一个地方闭环。

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
| `file_write` | 「把 B2 改成 2024」（文本全量替换，Office 按 ops 就地改） |
| `file_new` | 「给我写个脚本 / 出个周报」 |
| `file_send` | 「发给我」 |
| `file_pdf` | 「只留第 1-3 页」「把这份扫描件看清楚」「按新正文重排一份 PDF」 |
| `file_video_link` | 甩来一个 B 站／YouTube 链接问「这讲了什么」 |

改 Office 走「打开-改-保存」：Excel 只动指定单元格（列宽、公式、样式都在），
PPT 只改已有形状的文字（母版不动），Word 只改指定段落。
PDF 三种动作：`keep` 留页、`pages` 按页渲染识图、`rebuild` 全文重排（版式会丢，需提前说明）。

## 面板

插件卡「查看页面」进入，两个标签页：

- **文件**：左侧类型栏（没有文件的类型灰显），右侧表格；拖文件进窗口或点「上传」即可入库（8MB 分片，大文件也吃得下）；点行开抽屉——预览内容、在线改文本、版本历史回滚、下载、发到会话、删除。
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
| `enable_pdf_ocr` | 开 | PDF 无文字层时整页渲染识图 |
| `video_link_enabled` / `video_link_auto_delete` | 开 / 开 | 视频链接解析与用完即删 |
| `video_link_cookies` | 空 | 需要登录的平台填 cookies 文件绝对路径 |

## 限制（用之前先看这几条）

- **AstrBot 版本**：`>=4.16,<5`。用到插件页面与 `register_web_api`，更老的版本没有这两样。
- **直发文件依赖平台**：QQ（aiocqhttp / OneBot v11）需要 NapCat 且该会话可上传；其他平台走框架 `File` 组件，平台不支持直发时自动降级为「文件已在文枢」提示，不报错。
- **在线编辑只对文本类**（文本 / Markdown / 代码 / CSV）。Office 与 PDF 不在线改版式，只给下载、就地改、版本回滚。
- **旧版 Office（`.doc/.xls/.ppt`）** 只能入库与下载，不能解析内容——请转成新版格式。
- **PDF 重排**（`rebuild`）只保证文字内容，原版式、字体、图片一律丢失。
- **视频**：本地文件按全长均匀抽帧（默认 8 帧）；链接靠 `yt-dlp` 临时下载，抖音等平台要自备 cookies，下载失败会明说原因。
- **依赖**：`python-pptx`、`reportlab`、`pypdf`、`pypdfium2`、`yt-dlp`（`requirements.txt` 自动装）；抽帧需要容器内有 `ffmpeg`。

## 目录结构

```
data/plugin_data/astrbot_plugin_doc_hub/
├─ index.db                      元数据
├─ files/<会话>/<年-月>/<原名>.<id>.<ext>   最新版，人眼可读
├─ versions/<id>/vN.<ext>        历史版本
└─ temp/                         抽帧、上传分片、导出临时物
```

## 开发

```bash
python -m unittest tests.test_store -v
```

作者：沐倾
