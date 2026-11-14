import os
import uuid
import shutil
import tempfile
import glob
from typing import Optional, Dict, List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from src.config import BeautifyConfig
from src.epub_parser import EpubParser
from src.processor import EpubProcessor
from src.css_builder import build_beautified_css

app = FastAPI(title="EPUB Auto-Beautifier API")

# 全局任务状态，格式：{task_id: {"status": "processing", "progress": 0, "message": "", "result": None}}
EXPORT_TASKS = {}
# 模板提取信息的全局缓存，格式：{abs_path: {"mtime": 0.0, "rules": {}, "css_content": "", "fonts": []}}
TEMPLATE_CACHE = {}

# 获取系统临时目录并构建专属项目上传暂存区
TEMP_UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "epub_beautify_uploads")
os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)
os.makedirs("fonts", exist_ok=True)

# 确保 web 静态资源目录存在，防止 app.mount 报错
os.makedirs(os.path.join("web", "static"), exist_ok=True)

class PreviewRequest(BaseModel):
    temp_file_path: str
    line_height: float
    text_indent: str
    margin_bottom: str
    font_family: str
    custom_font: Optional[str] = None  # 自定义字体文件名 (例如 LXGWWenKaiLite-Regular.ttf)
    convert_to_simplified: bool
    target_device: str
    chapter_path: str  # 当前预览的章节路径
    raw_html: str      # 该章节对应的原始 HTML 字符
    # 核心清洗选项
    remove_empty_paragraphs: bool = True
    clean_inline_styles: bool = True
    clean_spans: bool = True
    clean_divs: bool = True
    auto_detect_titles: bool = False
    wrap_images: bool = False
    auto_page_break_h: bool = False
    # 模板套用选项
    use_template: bool = False
    template_filename: Optional[str] = None

class ExportRequest(BaseModel):
    temp_file_path: str
    line_height: float
    text_indent: str
    margin_bottom: str
    font_family: str
    custom_font: Optional[str] = None  # 自定义字体文件名 (例如 LXGWWenKaiLite-Regular.ttf)
    convert_to_simplified: bool
    target_device: str
    # 核心清洗选项
    remove_empty_paragraphs: bool = True
    clean_inline_styles: bool = True
    clean_spans: bool = True
    clean_divs: bool = True
    auto_detect_titles: bool = False
    wrap_images: bool = False
    auto_page_break_h: bool = False
    # 模板套用选项
    use_template: bool = False
    template_filename: Optional[str] = None

def _fast_convert_preview_footnotes(html_content: str, icon_rel_path: str = None) -> str:
    """
    内存极速单章弹注转换器：1 毫秒内完成单章 HTML 节点的弹注图标升轨与替换，实现 Web 面板极速秒刷。
    """
    if not html_content or ("[" not in html_content and "noteref" not in html_content):
        return html_content
    try:
        soup = BeautifulSoup(html_content, "xml")
        modified = False
        
        # 1. 匹配正文中的超链接 a 标签
        anchors = soup.find_all("a", href=True)
        for a in anchors:
            txt = a.get_text(strip=True)
            href = a.get("href", "")
            if "#" in href and (re.match(r'^\[?\d+\]?$', txt) or "note" in href.lower() or "fn" in href.lower() or "ch" in href.lower()):
                a["epub:type"] = "noteref"
                a["class"] = ["duokan-footnote"]
                a["style"] = "text-decoration:none!important;color:black;"
                if icon_rel_path:
                    a.string = ""
                    img_tag = soup.new_tag("img", alt="note", src=icon_rel_path)
                    a.append(img_tag)
                modified = True
                
        # 2. 匹配未被 a 包裹的静态文本角标 [1], [2]
        if icon_rel_path:
            for p in soup.find_all(["p", "sup", "span"]):
                txt = p.get_text()
                if re.search(r'\[\d+\]', txt):
                    for child in list(p.children):
                        child_txt = child.get_text().strip() if hasattr(child, "get_text") else str(child).strip()
                        m = re.search(r'\[(\d+)\]', child_txt)
                        if m:
                            num = m.group(1)
                            new_a = soup.new_tag("a", href=f"#note_{num}", attrs={
                                "class": "duokan-footnote",
                                "epub:type": "noteref",
                                "id": f"noteref_note_{num}",
                                "style": "text-decoration:none!important;color:black;"
                            })
                            img_tag = soup.new_tag("img", alt="note", src=icon_rel_path)
                            new_a.append(img_tag)
                            child.replace_with(new_a)
                            modified = True
                            break
        return str(soup) if modified else html_content
    except Exception:
        return html_content

@app.post("/api/upload")
async def upload_epub(file: UploadFile = File(...)):
    """
    处理 EPUB 文件上传，解压到临时目录，并读取书籍结构与全章节路径列表返回前端。
    """
    if not file.filename.endswith(".epub"):
        raise HTTPException(status_code=400, detail="只允许上传 .epub 格式的电子书文件。")

    # 生成唯一的临时文件名以防并发覆盖
    file_id = str(uuid.uuid4())
    temp_path = os.path.join(TEMP_UPLOAD_DIR, f"{file_id}.epub")
    unzipped_dir = os.path.join(TEMP_UPLOAD_DIR, f"{file_id}_unzipped")

    try:
        # 保存上传的文件到暂存目录
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 全书解压缩到临时静态路由目录下，供网页端高保真预览图片
        import zipfile
        os.makedirs(unzipped_dir, exist_ok=True)
        with zipfile.ZipFile(temp_path, 'r') as z_in:
            z_in.extractall(unzipped_dir)

        # 解析书籍元数据与所有的章节路径
        with EpubParser(temp_path) as parser:
            metadata = parser.metadata
            spine_paths = parser.spine_paths
            opf_dir = parser.opf_dir

        # 写入初始的默认精排样式表到解压目录下，供预览静态加载
        default_css = build_beautified_css(BeautifyConfig())
        temp_opf_dir = os.path.join(unzipped_dir, opf_dir) if opf_dir else unzipped_dir
        os.makedirs(temp_opf_dir, exist_ok=True)
        with open(os.path.join(temp_opf_dir, "global_style.css"), "w", encoding="utf-8") as f:
            f.write(default_css)

        return {
            "success": True,
            "file_id": file_id,
            "temp_file_path": temp_path,
            "title": metadata.get("title", "未知书名"),
            "creator": metadata.get("creator", "未知作者"),
            "spine_paths": spine_paths
        }

    except Exception as e:
        # 异常情况及时清理脏文件
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if os.path.exists(unzipped_dir):
            shutil.rmtree(unzipped_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"解析 EPUB 失败: {str(e)}")

@app.get("/api/chapter")
async def get_chapter_content(file_id: str, chapter_path: str):
    """
    拉取已经解压的临时书籍中指定章节的内容，供网页端按需渲染。
    """
    unzipped_dir = os.path.join(TEMP_UPLOAD_DIR, f"{file_id}_unzipped")
    target_file = os.path.join(unzipped_dir, chapter_path)
    
    if not os.path.exists(target_file):
        raise HTTPException(status_code=404, detail=f"未找到指定的章节文件: {chapter_path}")
        
    try:
        content_bytes = b""
        with open(target_file, "rb") as f:
            content_bytes = f.read()
            
        try:
            content_str = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            content_str = content_bytes.decode("gbk", errors="ignore")
            
        return {
            "success": True,
            "content": content_str
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取章节内容失败: {str(e)}")

@app.post("/api/beautify_preview")
async def beautify_preview(req: PreviewRequest):
    """
    内存级精排预览：在内存中清洗 HTML 的同时，直接将用户变动的精排参数生成 CSS 并覆盖写入临时解压目录下，供 iframe 静态拉取。
    """
    config = BeautifyConfig(
        line_height=req.line_height,
        text_indent=req.text_indent,
        margin_bottom=req.margin_bottom,
        font_family=req.font_family,
        custom_font=req.custom_font, # 传入自定义字体参数
        convert_to_simplified=req.convert_to_simplified,
        target_device=req.target_device,
        remove_empty_paragraphs=req.remove_empty_paragraphs,
        clean_inline_styles=req.clean_inline_styles,
        clean_spans=req.clean_spans,
        clean_divs=req.clean_divs,
        auto_detect_titles=req.auto_detect_titles,
        wrap_images=req.wrap_images,
        auto_page_break_h=req.auto_page_break_h
    )
    
    try:
        # 内存级清洗 HTML 并返回
        processor = EpubProcessor(config)
        
        file_id = os.path.basename(req.temp_file_path).replace(".epub", "")
        unzipped_dir = os.path.join(TEMP_UPLOAD_DIR, f"{file_id}_unzipped")
        
        # 获取该书的 OPF 目录
        parser = EpubParser(req.temp_file_path)
        parser.open()
        opf_dir = parser.opf_dir
        parser.close()
            
        temp_opf_dir = os.path.join(unzipped_dir, opf_dir) if opf_dir else unzipped_dir
        os.makedirs(temp_opf_dir, exist_ok=True)
        
        if req.use_template:
            template_path = None
            if req.template_filename:
                template_path = os.path.join(os.getcwd(), "example", req.template_filename)
            else:
                example_dir = os.path.join(os.getcwd(), "example")
                epub_files = glob.glob(os.path.join(example_dir, "*.epub"))
                if epub_files:
                    epub_files.sort(key=os.path.getmtime, reverse=True)
                    template_path = epub_files[0]
            
            if not template_path or not os.path.exists(template_path):
                raise HTTPException(status_code=400, detail="未找到排版模板文件，请确保根目录 example 文件夹下已放入 EPUB 模板。")
                
            # 模板缓存与提取
            mtime = os.path.getmtime(template_path)
            cache_key = os.path.abspath(template_path)
            cache_output_dir = os.path.join(tempfile.gettempdir(), "epub_template_cache")
            os.makedirs(cache_output_dir, exist_ok=True)
            
            if cache_key not in TEMPLATE_CACHE or TEMPLATE_CACHE[cache_key]["mtime"] != mtime:
                from src.template_extractor import TemplateExtractor
                extractor = TemplateExtractor()
                t_data = extractor.extract_template(template_path, cache_output_dir)
                TEMPLATE_CACHE[cache_key] = {
                    "mtime": mtime,
                    "rules": t_data["rules"],
                    "css_content": t_data["css_content"],
                    "fonts": t_data["fonts"],
                    "images": t_data.get("images", [])
                }
                
            template_info = TEMPLATE_CACHE[cache_key]
            rules = template_info["rules"]
            css_content = template_info["css_content"]
            extracted_fonts = template_info["fonts"]
            extracted_images = template_info.get("images", [])
            
            # 将模板字体物理拷贝到当前预览书籍的 fonts 目录下以供预览加载
            if extracted_fonts:
                preview_fonts_dir = os.path.join(temp_opf_dir, "fonts")
                os.makedirs(preview_fonts_dir, exist_ok=True)
                source_fonts_dir = os.path.join(cache_output_dir, "fonts")
                if os.path.exists(source_fonts_dir):
                    for font_name in extracted_fonts:
                        shutil.copy2(os.path.join(source_fonts_dir, font_name), os.path.join(preview_fonts_dir, font_name))
                        
            icon_image_name = None
            if extracted_images:
                preview_imgs_dir = os.path.join(temp_opf_dir, "Images")
                os.makedirs(preview_imgs_dir, exist_ok=True)
                source_imgs_dir = os.path.join(cache_output_dir, "images")
                if os.path.exists(source_imgs_dir):
                    for img_name in extracted_images:
                        shutil.copy2(os.path.join(source_imgs_dir, img_name), os.path.join(preview_imgs_dir, img_name))
                        if not icon_image_name or "note" in img_name.lower():
                            icon_image_name = img_name

            beautified_html = processor.cleaner.clean_html_with_template(
                html_content=req.raw_html,
                css_rel_path="global_style.css",
                template_rules=rules,
                inline_css_content=None,
                current_html_path=req.chapter_path
            )

            # 极速内存单章弹注转换（1 毫秒毫秒级秒刷，彻底消灭界面卡顿）
            icon_rel_path = None
            if icon_image_name and req.chapter_path:
                chap_abs_path = os.path.join(unzipped_dir, req.chapter_path)
                html_dir = os.path.dirname(chap_abs_path)
                imgs_dir = os.path.join(temp_opf_dir, "Images")
                icon_abs_path = os.path.join(imgs_dir, icon_image_name)
                icon_rel_path = os.path.relpath(icon_abs_path, html_dir).replace('\\', '/')

            beautified_html = _fast_convert_preview_footnotes(beautified_html, icon_rel_path)
        else:
            beautified_html = processor.preview_beautify(req.raw_html, "global_style.css")
            
            # 根据当前配置生成全新的样式表
            css_content = build_beautified_css(config, is_preview=True)
            
            # 融合原书核心保留排版规则（加粗、字号、段落外边距、对齐）
            original_rules = processor._extract_original_css_rules(unzipped_dir)
            if original_rules:
                css_content += "\n\n/* --- 融合原书核心保留排版规则 --- */\n" + original_rules
            
        with open(os.path.join(temp_opf_dir, "global_style.css"), "w", encoding="utf-8") as f:
            f.write(css_content)

        return {
            "success": True,
            "beautified_html": beautified_html,
            "css_content": css_content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"排版效果刷新失败: {str(e)}")

def safe_filename(name):
    # 将非法文件名字符过滤为下划线
    return "".join(c if c.isalnum() or c in "._- ()[]（）【】" else "_" for c in name)

import threading

def run_export_task(task_id: str, req: ExportRequest):
    try:
        config = BeautifyConfig(
            line_height=req.line_height,
            text_indent=req.text_indent,
            margin_bottom=req.margin_bottom,
            font_family=req.font_family,
            custom_font=req.custom_font, # 传入自定义字体参数
            convert_to_simplified=req.convert_to_simplified,
            target_device=req.target_device,
            remove_empty_paragraphs=req.remove_empty_paragraphs,
            clean_inline_styles=req.clean_inline_styles,
            clean_spans=req.clean_spans,
            clean_divs=req.clean_divs,
            auto_detect_titles=req.auto_detect_titles,
            wrap_images=req.wrap_images,
            auto_page_break_h=req.auto_page_break_h
        )
        
        # 1. 获取书籍标题，确保最友好的保存名称
        book_title = "beautified_book"
        try:
            with EpubParser(req.temp_file_path) as parser:
                book_title = parser.metadata.get("title", "beautified_book")
        except Exception:
            pass
            
        safe_title = safe_filename(book_title)
        output_filename = f"beautified_{safe_title}.epub"
        
        # 写入根目录下 (工作目录)
        root_output_path = os.path.join(os.getcwd(), output_filename)
        
        # 2. 声明进度回调
        def progress_cb(progress, message):
            if task_id in EXPORT_TASKS:
                EXPORT_TASKS[task_id]["progress"] = progress
                EXPORT_TASKS[task_id]["message"] = message

        # 3. 开始执行精排
        processor = EpubProcessor(config)
        
        # 使用随机临时文件做中间打包，以保全原有文件不冲突
        temp_out_id = str(uuid.uuid4())
        temp_output_path = os.path.join(TEMP_UPLOAD_DIR, f"out_{temp_out_id}.epub")
        
        # 确定模板路径
        template_path = None
        if req.use_template:
            if req.template_filename:
                template_path = os.path.join(os.getcwd(), "example", req.template_filename)
            else:
                example_dir = os.path.join(os.getcwd(), "example")
                epub_files = glob.glob(os.path.join(example_dir, "*.epub"))
                if epub_files:
                    epub_files.sort(key=os.path.getmtime, reverse=True)
                    template_path = epub_files[0]
            if not template_path or not os.path.exists(template_path):
                raise FileNotFoundError("未找到指定的模板 EPUB 电子书，请核对 example 目录。")
        
        if template_path:
            processor.beautify_epub_with_template(req.temp_file_path, temp_output_path, template_path, progress_callback=progress_cb)
        else:
            processor.beautify_epub(req.temp_file_path, temp_output_path, progress_callback=progress_cb)
        
        # 排版结束后，安全原子性重命名并移动到根目录下
        if os.path.exists(temp_output_path):
            if os.path.exists(root_output_path):
                os.remove(root_output_path)  # 若根目录下原有文件已存在则覆盖
            shutil.move(temp_output_path, root_output_path)
            
        EXPORT_TASKS[task_id].update({
            "status": "success",
            "progress": 100,
            "message": "精排打包完成！已完美保存至项目根目录！",
            "result": output_filename
        })
        
    except Exception as e:
        import traceback
        EXPORT_TASKS[task_id].update({
            "status": "failed",
            "message": f"排版出错: {str(e)}",
            "error": traceback.format_exc()
        })

@app.post("/api/export")
async def export_epub(req: ExportRequest):
    """
    全书完整重排导出：在后台线程中启动全书精排任务，并立即返回任务 ID 以供轮询。
    """
    if not os.path.exists(req.temp_file_path):
        raise HTTPException(status_code=404, detail="上传的文件已过期或被清理，请重新拖入文件。")

    task_id = str(uuid.uuid4())
    EXPORT_TASKS[task_id] = {
        "status": "processing",
        "progress": 0,
        "message": "正在准备精排环境...",
        "result": None
    }
    
    # 启动后台任务进程
    thread = threading.Thread(target=run_export_task, args=(task_id, req))
    thread.daemon = True
    thread.start()

    return {
        "success": True,
        "task_id": task_id
    }

@app.get("/api/export_status/{task_id}")
async def get_export_status(task_id: str):
    """
    前端定时轮询此接口获取任务进度和精排结果。
    """
    if task_id not in EXPORT_TASKS:
        raise HTTPException(status_code=404, detail="未找到该精排导出任务。")
    return EXPORT_TASKS[task_id]

# 挂载前端 index 路由
@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = os.path.join("web", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>前端 index.html 正在努力渲染中，请稍等...</h3>"

@app.get("/api/fonts")
async def get_available_fonts():
    """
    动态扫描 fonts/ 目录，将所有已下载的自定义字体文件返回前端。
    """
    fonts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fonts"))
    os.makedirs(fonts_dir, exist_ok=True)
    supported_extensions = (".ttf", ".otf", ".woff2")
    font_files = []
    
    for file in os.listdir(fonts_dir):
        if file.lower().endswith(supported_extensions):
            name_map = {
                "LXGWWenKaiLite-Regular.ttf": "霞鹜文楷 Lite",
                "LXGWWenKaiGB-Regular.ttf": "霞鹜文楷 GB",
                "LXGWWenKaiTC-Regular.ttf": "霞鹜文楷 TC",
                "TsangerJinKai01-W03.ttf": "仓耳今楷"
            }
            display_name = name_map.get(file, os.path.splitext(file)[0])
            font_files.append({
                "name": display_name,
                "filename": file
            })
            
    return {
        "success": True,
        "fonts": font_files
    }

@app.get("/api/templates")
async def get_available_templates():
    """
    扫描根目录下的 example/ 目录，获取可用的模板 EPUB 电子书列表。
    """
    example_dir = os.path.join(os.getcwd(), "example")
    os.makedirs(example_dir, exist_ok=True)
    epub_files = glob.glob(os.path.join(example_dir, "*.epub"))
    
    templates = []
    # 按照最后修改时间排序
    epub_files.sort(key=os.path.getmtime, reverse=True)
    for path in epub_files:
        filename = os.path.basename(path)
        templates.append({
            "filename": filename,
            "title": filename.replace(".epub", ""),
            "mtime": os.path.getmtime(path)
        })
        
    return {
        "success": True,
        "templates": templates
    }

# 挂载静态资源服务
app.mount("/static", StaticFiles(directory=os.path.join("web", "static")), name="static")

# 挂载解压电子书临时预览目录，以便双栏 iframe 内部相对图片路径能够正常静态寻址
app.mount("/temp_preview", StaticFiles(directory=TEMP_UPLOAD_DIR), name="temp_preview")

# 挂载自定义字体目录，方便预览 iframe 静态加载字体
app.mount("/fonts", StaticFiles(directory=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fonts"))), name="fonts")

@app.get("/{file_name:path}")
async def serve_fallback_static_assets(file_name: str):
    """
    通用静态资源回退兜底路由：
    当预览 iframe 或内联 CSS 误向根域名请求图片/CSS/字体 (如 /flow0001.css 或 /Image00002.jpg) 时，
    自动在临时上传暂存区的最新解压目录中进行深度物理寻址并返回，彻底粉碎 404 日志。
    """
    if file_name.startswith("api/") or file_name.startswith("static/") or file_name.startswith("temp_preview/") or file_name.startswith("fonts/"):
        raise HTTPException(status_code=404, detail="Not found")

    subdirs = [os.path.join(TEMP_UPLOAD_DIR, d) for d in os.listdir(TEMP_UPLOAD_DIR) if d.endswith("_unzipped")]
    if not subdirs:
        raise HTTPException(status_code=404, detail="No active unzipped ebook found")

    subdirs.sort(key=os.path.getmtime, reverse=True)
    target_basename = os.path.basename(file_name)

    for latest_dir in subdirs:
        matched_files = glob.glob(os.path.join(latest_dir, "**", target_basename), recursive=True)
        if matched_files:
            # 过滤掉样板提取缓存中的图片，只匹配目标书籍自身的图片
            matched_files = [f for f in matched_files if "epub_template_cache" not in f]
            if not matched_files:
                continue
            found_file = matched_files[0]
            ext = os.path.splitext(found_file)[1].lower()
            media_type = "application/octet-stream"
            if ext in [".jpg", ".jpeg"]: media_type = "image/jpeg"
            elif ext == ".png": media_type = "image/png"
            elif ext == ".svg": media_type = "image/svg+xml"
            elif ext == ".gif": media_type = "image/gif"
            elif ext == ".css": media_type = "text/css"
            elif ext in [".ttf", ".otf", ".woff2"]: media_type = "font/ttf"
            
            return FileResponse(found_file, media_type=media_type)

    raise HTTPException(status_code=404, detail=f"Asset {file_name} not found")
