# 文件读写小助手（astrbot_plugin_file_rw_assistant）

聊天里发过来的文件本来睡一觉就找不到了。这个插件把它们收进一个地方存着，
让模型能自己翻、自己读（扫描件也能看）、自己改、自己生成，改完直接发回聊天；
面板里点开就能看、能改、能删。

Word / Excel / PPT / PDF / 文本 / Markdown / 代码 / CSV / 视频都能收。
压缩包、图片、音频不收。

作者：沐倾

---

## 一、怎么装

1. 面板 → 插件 → 从仓库安装，填 `muqing-kg/astrbot_plugin_file_rw_assistant`。
2. 等依赖装完（`python-pptx`、`reportlab`、`pypdf`、`pypdfium2`、`yt-dlp`；`requirements.txt` 会自动 pip 安装）。
3. 刷新插件卡完成加载，日志里能看到加载完成。**依赖装完必须刷新一次**，否则首次加载会缺库。
4. 点插件卡上的「查看页面」进面板。

容器内需要 `ffmpeg` 才能抽视频帧（大多数镜像自带，没有就自己装进容器）。

## 二、怎么用

### 1. 丢文件进去

群里或私聊里直接发文件就行，不用命令。插件收到后按「会话 + 年月」归档，
文件名保留原样，同名不覆盖（后面缀 8 位编号），并在消息里补一句 `[文件读写小助手] …`，
模型当轮就能读到它。面板里也能拖文件进去，或点「上传」选文件——大文件按 8MB 分片传，不会卡住。

### 2. 跟它说话

| 想干的事 | 直接说 |
|---|---|
| 找文件 | 「刚才那个表在哪」「有哪些 Excel」 |
| 读内容 | 「这份 PDF 讲了什么」「把第三条念给我」 |
| 读扫描件 | 「这张扫描件上写的什么」 |
| 改单元格 | 「把 B2 改成 2024」 |
| 改 PPT | 「第 2 页标题换个说法」 |
| 改文档段落 | 「第三段删掉」 |
| 处理 PDF | 「只留第 1-3 页」「按这段新正文重排一份 PDF」 |
| 生成新文件 | 「写个周报 md 给我」「生成个统计脚本」 |
| 要回来 | 「发给我」「发群里」 |
| 看视频 | 「这个视频讲了什么」 |
| 看链接 | 「这个 B 站视频讲什么」+ 链接 |
| 删文件 | 去面板删（模型没有删除权限） |

模型不按类型背规则，它看文件类型自动选对读法。

### 3. 面板

插件卡「查看页面」→ 两个标签页：

- **文件**：左边是类型栏（没有文件的类型灰显，点一下切过去），右边表格列出名称/类型/大小/版本/来源/更新时间。
  点行开抽屉：预览内容、在线改文本存新版、翻版本历史回滚、下载、发到会话、删除。
- **设置**：跟插件配置页读写同一份配置，改完即生效。

## 三、七个工具（模型侧）

| 工具 | 作用 |
|---|---|
| `file_list(kind, keyword)` | 按类型/关键词列文件 |
| `file_read(file_id, version)` | 读内容：文本直读；docx/xlsx/pptx 解析；PDF 抽字，无文字层整页识图；视频抽帧描述 |
| `file_write(file_id, content, ops)` | 改：文本整体替换；Excel 按 `[{"sheet","cell","value"}]`、PPT 按 `[{"slide","shape","text"}]`、Word 按 `[{"paragraph","text"}]` 就地改并存新版 |
| `file_new(name, content)` | 新建文本类文件 |
| `file_send(file_id, version)` | 发回会话 |
| `file_pdf(file_id, action, pages, content)` | `keep` 留指定页 / `pages` 整页识图 / `rebuild` 按新正文重排 |
| `file_video_link(url, keep)` | 用 yt-dlp 临时下载后抽帧描述，默认用完即删 |

## 四、配置

| 项 | 默认 | 说明 |
|---|---|---|
| `retention_days` | 90 | 超过自动删，0 = 永久 |
| `max_versions` | 20 | 单文件版本上限，超了淘汰最旧 |
| `max_file_mb` / `max_video_mb` | 200 / 2048 | 单文件大小上限 |
| `video_frames` / `max_vision_images` | 8 / 6 | 抽帧数 / 单次识图张数 |
| `auto_cleanup` | 开 | 每 6 小时扫一次 |
| `storage_root` | 空 | 空 = 插件数据目录（跟着面板备份走）；填绝对路径则独立存放 |
| `text_model_provider_id` / `vision_model_provider_id` | 空 | 空 = 跟随框架当前模型 |
| `enable_pdf_ocr` | 开 | PDF 无文字层时整页渲染识图 |
| `video_link_enabled` / `video_link_auto_delete` | 开 / 开 | 链接解析开关与用完即删 |
| `video_link_cookies` | 空 | 需要登录的平台填 cookies 文件绝对路径 |

## 五、限制

- **AstrBot 版本** `>=4.16,<5`（用到插件页面与 `register_web_api`）。
- **直发文件靠平台**：QQ（aiocqhttp / OneBot v11）需 NapCat 且会话可上传；其他平台走框架 `File` 组件；平台不支持时只提示「文件在文件读写小助手里」，不报错、不丢文件。
- **在线编辑只对文本类**（文本 / Markdown / 代码 / CSV）。Office 与 PDF 不在线改版式，只给下载、就地改、版本回滚。
- **旧格式 `.doc/.xls/.ppt`** 只能入库与下载，解析不了，请转存为新格式。
- **Office 就地改**只能改写已有单元格/形状/段落的文字，不能新增行、新增形状、插图片。
- **PDF 重排**只保文字，版式、字体、图片全丢。
- **视频**：本地文件按全长均匀抽帧（默认 8 帧）；链接靠 `yt-dlp`，抖音等平台要自备 cookies，失败会明说原因。
- **不收**压缩包、图片、音频。

## 六、目录

```
data/plugin_data/astrbot_plugin_file_rw_assistant/
├─ index.db                                元数据（files / versions）
├─ files/<会话>/<年-月>/<原名>.<id>.<ext>   最新版，人眼可读
├─ versions/<id>/vN.<ext>                  历史版本
└─ temp/                                   抽帧、上传分片、导出临时物
```

## 七、开发

```bash
python -m unittest tests.test_store -v
```

七个用例覆盖：类型判定、入库与版本、版本上限淘汰、删除清盘、搜索与计数、文本/CSV 读取、分片上传拼接。
