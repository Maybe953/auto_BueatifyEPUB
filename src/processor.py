import os
import zipfile
import shutil
import tempfile
import re
import glob
import uuid
from src.config import BeautifyConfig
from src.epub_parser import EpubParser
from src.html_cleaner import HtmlCleaner
from src.css_builder import build_beautified_css

class EpubProcessor:
    def __init__(self, config: BeautifyConfig):
        self.config = config
        self.cleaner = HtmlCleaner(config)

    def beautify_epub(self, input_path: str, output_path: str, progress_callback=None):
        """
        核心精排流控制：解包 -> 解析结构 -> 清洗 -> 注入 -> 重新打包
        """
        if progress_callback:
            progress_callback(10, "正在初始化临时工作目录...")

        # 1. 建立临时解包目录
        with tempfile.TemporaryDirectory() as temp_dir:
            if progress_callback:
                progress_callback(20, "正在解压分析原始电子书...")
            
            # 解压原 epub 到临时目录
            with zipfile.ZipFile(input_path, 'r') as z:
                z.extractall(temp_dir)

            # 2. 用 EpubParser 解析结构
            parser = EpubParser(input_path)
            parser.open()

            opf_path = parser.opf_path
            temp_opf_path = os.path.join(temp_dir, opf_path)
            temp_opf_dir = os.path.dirname(temp_opf_path)

            spine_paths = parser.spine_paths
            ncx_path = parser.ncx_path

            # 3. 构建精排专属的 CSS 并融合原书样式
            if progress_callback:
                progress_callback(40, "正在提取并融合原书核心排版规则...")
            css_content = build_beautified_css(self.config, is_preview=False)
            
            # 扫描并提取原书中的核心加粗、对齐规则
            original_rules = self._extract_original_css_rules(temp_dir)
            if original_rules:
                css_content += "\n\n/* --- 融合原书核心保留排版规则 --- */\n" + original_rules

            css_filename = "global_style.css"
            temp_css_path = os.path.join(temp_opf_dir, css_filename)
            with open(temp_css_path, "w", encoding="utf-8") as f:
                f.write(css_content)

            # 3.2 物理拷贝自定义字体文件 (发烧友级硬核补缺，防止字体物理丢失)
            if self.config.custom_font:
                temp_fonts_dir = os.path.join(temp_opf_dir, "fonts")
                os.makedirs(temp_fonts_dir, exist_ok=True)
                
                project_font_path = os.path.join(os.getcwd(), "fonts", self.config.custom_font)
                temp_font_path = os.path.join(temp_fonts_dir, self.config.custom_font)
                
                if os.path.exists(project_font_path):
                    shutil.copy2(project_font_path, temp_font_path)
                    print(f"[+] Physical copy custom font successful: {self.config.custom_font}")
                else:
                    print(f"[-] Physical font NOT found at: {project_font_path}")

            # 3.5 识别要物理剔除的目录章节并建立重定向映射字典
            toc_item_ids = parser.get_toc_item_ids()
            toc_rel_paths = []
            for item_id in toc_item_ids:
                item_info = parser.manifest.get(item_id)
                if item_info:
                    toc_rel_paths.append(parser._resolve_path(item_info['href']))
            
            # 计算一对一精准重定向映射表：每一个被剔除的物理目录，都智能定向至其各自对应分册的合法封面/正文首章 (统一正斜杠以防止跨平台斜杠比对失效，并使用原始Spine索引定位)
            redirect_map = {}
            for rel_path in toc_rel_paths:
                if rel_path in parser.original_spine_paths:
                    idx = parser.original_spine_paths.index(rel_path)
                    target = None
                    # 往后寻找紧挨着的非目录章节
                    for next_path in parser.original_spine_paths[idx+1:]:
                        if next_path not in toc_rel_paths:
                            target = next_path
                            break
                    if not target:
                        # 兜底：往前寻找非目录章节
                        for prev_path in reversed(parser.original_spine_paths[:idx]):
                            if prev_path not in toc_rel_paths:
                                target = prev_path
                                break
                    if target:
                        redirect_map[rel_path.replace('\\', '/')] = target.replace('\\', '/')

            # 4. 遍历并清洗所有的章节 XHTML 文件 (物理目录章节被剔除出清洗流)
            for idx, html_rel_path in enumerate(spine_paths):
                if html_rel_path in toc_rel_paths:
                    # 剔除的物理目录直接跳过清洗与写回
                    continue

                if progress_callback:
                    percent = int(20 + 60 * (idx + 1) / len(spine_paths))
                    progress_callback(percent, f"正在精排清洗章节 ({idx+1}/{len(spine_paths)}): {os.path.basename(html_rel_path)}...")
                temp_html_path = os.path.join(temp_dir, html_rel_path)
                if not os.path.exists(temp_html_path):
                    continue

                # 计算当前 HTML 文件相对于 OPF 目录下 global_style.css 的相对路径
                html_dir = os.path.dirname(temp_html_path)
                rel_css_dir = os.path.relpath(temp_opf_dir, html_dir)
                rel_css_path = os.path.join(rel_css_dir, css_filename).replace('\\', '/')

                # 读取、清洗并写回
                try:
                    with open(temp_html_path, "r", encoding="utf-8", errors="ignore") as f:
                        html_content = f.read()
                        
                    cleaned_content = self.cleaner.clean_html(
                        html_content, 
                        rel_css_path, 
                        current_html_path=html_rel_path, 
                        redirect_map=redirect_map
                    )
                    
                    with open(temp_html_path, "w", encoding="utf-8") as f:
                        f.write(cleaned_content)
                except Exception as e:
                    print(f"清洗章节 {html_rel_path} 失败: {str(e)}")
                    continue

            # 智能转换弹出式注释 (Footnote Popups)
            try:
                if progress_callback:
                    progress_callback(75, "正文清洗完成，正在自动识别并转换弹出式注释...")
                from src.footnote_converter import FootnoteConverter
                converter = FootnoteConverter()
                converter.convert_footnotes(temp_dir)
            except Exception as e:
                print(f"[*] 弹注转换发生错误: {e}")

            if progress_callback:
                progress_callback(80, "弹注转换完成，正在注入精排样式表并隐藏物理目录...")

            # 5. 更新 content.opf 注册我们的新 CSS 文件，并彻底剥离物理目录，同步重定向修改 toc.ncx 元数据
            temp_opf_path = os.path.join(temp_dir, opf_path)
            temp_ncx_path = os.path.join(temp_dir, parser.ncx_path) if parser.ncx_path else None
            
            # 提前在纯相对路径层面上计算出重定向目标相对于 OPF/NCX 的相对 href 映射表，规避跨 Windows 挂载盘符计算时的 ValueError 崩溃
            opf_dir_rel = os.path.dirname(opf_path)
            opf_redirect_map = {}
            for k, v in redirect_map.items():
                k_href = os.path.relpath(k, opf_dir_rel).replace('\\', '/')
                v_href = os.path.relpath(v, opf_dir_rel).replace('\\', '/')
                opf_redirect_map[k_href] = v_href
                
            if os.path.exists(temp_opf_path):
                self._update_opf_manifest(
                    temp_opf_path, 
                    css_filename, 
                    toc_item_ids, 
                    self.config.custom_font, 
                    temp_ncx_path,
                    redirect_map=opf_redirect_map
                )

            if progress_callback:
                progress_callback(90, "样式注入成功，正在进行重构压缩打包...")

            # 6. 打包输出
            self._pack_epub(temp_dir, output_path)
            
            if progress_callback:
                progress_callback(100, "精排编译重构已全部完成！")

    def preview_beautify(self, raw_html: str, rel_css_path: str = "global_style.css") -> str:
        """
        仅在内存中精排单个 HTML 片段，用于 Web UI 实时左右对比预览。
        """
        return self.cleaner.clean_html(raw_html, rel_css_path)

    def beautify_epub_with_template(self, input_path: str, output_path: str, template_path: str, progress_callback=None):
        """
        基于模板 EPUB 克隆的精排处理流：
        1. 提取模板的样式、字体、特征规则
        2. 解压待处理 EPUB
        3. 用 TemplateHtmlCleaner 进行语义化清洗与样式重映射
        4. 物理拷贝并注册模板字体
        5. 压缩打包
        """
        if progress_callback:
            progress_callback(5, "正在初始化模板提取器...")

        from src.template_extractor import TemplateExtractor
        extractor = TemplateExtractor()
        
        # 我们用临时目录来提取模板的字体和CSS
        with tempfile.TemporaryDirectory() as temp_template_dir:
            if progress_callback:
                progress_callback(15, f"正在分析模板电子书: {os.path.basename(template_path)} ...")
                
            try:
                template_data = extractor.extract_template(template_path, temp_template_dir)
            except Exception as e:
                raise RuntimeError(f"解析模板 EPUB 失败: {str(e)}")

            rules = template_data["rules"]
            css_content = template_data["css_content"]
            extracted_fonts = template_data["fonts"]
            extracted_images = template_data.get("images", [])

            if progress_callback:
                progress_callback(30, "正在解压分析目标电子书...")

            # 1. 建立目标临时解包目录
            with tempfile.TemporaryDirectory() as temp_dir:
                # 解压原 epub 到临时目录
                with zipfile.ZipFile(input_path, 'r') as z:
                    z.extractall(temp_dir)

                # 2. 用 EpubParser 解析结构
                parser = EpubParser(input_path)
                parser.open()

                opf_path = parser.opf_path
                temp_opf_path = os.path.join(temp_dir, opf_path)
                temp_opf_dir = os.path.dirname(temp_opf_path)

                spine_paths = parser.spine_paths
                ncx_path = parser.ncx_path

                # 3. 写入模板 CSS 文件到 OPF 目录
                css_filename = "global_style.css"
                temp_css_path = os.path.join(temp_opf_dir, css_filename)
                with open(temp_css_path, "w", encoding="utf-8") as f:
                    f.write(css_content)

                # 4. 拷贝提取到的字体与图片文件到目标 EPUB 对应位置
                if extracted_fonts:
                    target_fonts_dir = os.path.join(temp_opf_dir, "fonts")
                    os.makedirs(target_fonts_dir, exist_ok=True)
                    source_fonts_dir = os.path.join(temp_template_dir, "fonts")
                    if os.path.exists(source_fonts_dir):
                        for font_name in extracted_fonts:
                            shutil.copy2(os.path.join(source_fonts_dir, font_name), os.path.join(target_fonts_dir, font_name))
                            print(f"[+] Physical copy template font successful: {font_name}")

                icon_image_name = None
                if extracted_images:
                    target_imgs_dir = os.path.join(temp_opf_dir, "Images")
                    os.makedirs(target_imgs_dir, exist_ok=True)
                    source_imgs_dir = os.path.join(temp_template_dir, "images")
                    if os.path.exists(source_imgs_dir):
                        for img_name in extracted_images:
                            shutil.copy2(os.path.join(source_imgs_dir, img_name), os.path.join(target_imgs_dir, img_name))
                            print(f"[+] Physical copy template image successful: {img_name}")
                            if not icon_image_name or "note" in img_name.lower():
                                icon_image_name = img_name

                # 5. 识别要物理剔除的目录章节并建立重定向映射字典
                toc_item_ids = parser.get_toc_item_ids()
                toc_rel_paths = []
                for item_id in toc_item_ids:
                    item_info = parser.manifest.get(item_id)
                    if item_info:
                        toc_rel_paths.append(parser._resolve_path(item_info['href']))
                
                redirect_map = {}
                for rel_path in toc_rel_paths:
                    if rel_path in parser.original_spine_paths:
                        idx = parser.original_spine_paths.index(rel_path)
                        target = None
                        for next_path in parser.original_spine_paths[idx+1:]:
                            if next_path not in toc_rel_paths:
                                target = next_path
                                break
                        if not target:
                            for prev_path in reversed(parser.original_spine_paths[:idx]):
                                if prev_path not in toc_rel_paths:
                                    target = prev_path
                                    break
                        if target:
                            redirect_map[rel_path.replace('\\', '/')] = target.replace('\\', '/')

                # 6. 核心：运行高级 HTML 规则清洗与语义格式转换
                if progress_callback:
                    progress_callback(50, "正在清洗和重构章节 HTML...")

                # 物理清除原书残留的旧 CSS 物理文件，确保全书 100% 仅应用模板精致纯黑样式
                for old_css in glob.glob(os.path.join(temp_dir, "**/*.css"), recursive=True):
                    if not old_css.endswith("template_style.css") and not old_css.endswith("global_style.css"):
                        try:
                            os.remove(old_css)
                        except Exception:
                            pass

                rules = template_data["rules"]
                for i, html_rel_path in enumerate(parser.spine_paths):
                    if html_rel_path in toc_rel_paths:
                        continue
                    
                    temp_html_path = os.path.join(temp_dir, html_rel_path)
                    if not os.path.exists(temp_html_path):
                        continue

                    if progress_callback and len(parser.spine_paths) > 0:
                        pct = 50 + int((i / len(parser.spine_paths)) * 30)
                        progress_callback(pct, f"正在套用模板精排章节 ({i+1}/{len(parser.spine_paths)})...")

                    html_dir = os.path.dirname(temp_html_path)
                    rel_css_dir = os.path.relpath(temp_opf_dir, html_dir)
                    rel_css_path = os.path.join(rel_css_dir, css_filename).replace('\\', '/')

                    try:
                        with open(temp_html_path, "r", encoding="utf-8", errors="ignore") as f:
                            html_content = f.read()
                            
                        cleaned_content = self.cleaner.clean_html_with_template(
                            html_content=html_content,
                            css_rel_path=rel_css_path,
                            template_rules=rules,
                            inline_css_content=None,
                            current_html_path=html_rel_path,
                            redirect_map=redirect_map
                        )
                        
                        with open(temp_html_path, "w", encoding="utf-8") as f:
                            f.write(cleaned_content)
                    except Exception as e:
                        print(f"清洗章节 {html_rel_path} 失败: {str(e)}")
                        continue

                # 7. 多看/Kobo 高保真图标弹出式注释处理
                try:
                    if progress_callback:
                        progress_callback(85, "正文清洗完成，正在重构多看/Kobo 标准图标弹出式注释...")
                    from src.footnote_converter import FootnoteConverter
                    converter = FootnoteConverter()
                    
                    # 计算图标相对于章节 HTML 的相对路径
                    icon_rel_path = f"../Images/{icon_image_name}" if icon_image_name else None
                    converter.convert_footnotes(temp_dir, use_template=True, icon_img_rel_path=icon_rel_path)
                except Exception as e:
                    print(f"[*] 弹注转换发生错误: {e}")

                if progress_callback:
                    progress_callback(90, "注入模板样式表并更新 Package Manifest...")
                temp_opf_path = os.path.join(temp_dir, opf_path)
                temp_ncx_path = os.path.join(temp_dir, parser.ncx_path) if parser.ncx_path else None
                
                opf_dir_rel = os.path.dirname(opf_path)
                opf_redirect_map = {}
                for k, v in redirect_map.items():
                    k_href = os.path.relpath(k, opf_dir_rel).replace('\\', '/')
                    v_href = os.path.relpath(v, opf_dir_rel).replace('\\', '/')
                    opf_redirect_map[k_href] = v_href
                    
                if os.path.exists(temp_opf_path):
                    self._update_opf_manifest(
                        opf_path=temp_opf_path, 
                        css_filename=css_filename, 
                        toc_item_ids=toc_item_ids, 
                        custom_fonts=extracted_fonts, 
                        ncx_path=temp_ncx_path,
                        redirect_map=opf_redirect_map
                    )

                if progress_callback:
                    progress_callback(95, "样式注入成功，正在进行重构压缩打包...")

                # 8. 打包输出
                self._pack_epub(temp_dir, output_path)
                
                if progress_callback:
                    progress_callback(100, "模板克隆已全部完成！")

    def _update_opf_manifest(self, opf_path: str, css_filename: str, toc_item_ids: list = None, custom_font: str = None, ncx_path: str = None, redirect_map: dict = None, custom_fonts: list = None, custom_images: list = None):
        """
        使用高效、稳定的正则表达式修改 OPF 文件的 Manifest 结构，规避 XML Tree 写回时的命名空间混淆风险。
        同时，如果传入了物理目录的 item_ids，会将它们从 spine 节点中彻底剥离删除以隐藏常规翻页。
        """
        with open(opf_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # 注入多看特有 meta 标签，强行激活多看高级排版引擎（这是多看识别高级弹注的隐藏开关）
        duokan_meta = '\n    <meta content="DK-SONGTI" name="duokan-body-font"/>\n    <meta content="DK-SONGTI" name="duokan-fallback-font"/>\n'
        content = re.sub(r'(<metadata[^>]*>)', rf'\1{duokan_meta}', content, flags=re.IGNORECASE)

        # 0. 提前提取物理目录在 manifest 里的原始相对路径 href 列表 (用于后续 guide 修正与 NCX 剔除)
        toc_hrefs = []
        if toc_item_ids:
            for item_id in toc_item_ids:
                # 匹配包含特定 id 的整个 <item .../> 标签
                pattern_item = rf'<item\s+[^>]*id=["\']{re.escape(item_id)}["\'][^>]*/>'
                match_item = re.search(pattern_item, content, re.IGNORECASE)
                if match_item:
                    item_str = match_item.group(0)
                    # 从提取出的标签文本中检索 href 的值
                    match_href = re.search(r'href\s*=\s*["\'](.*?)["\']', item_str, re.IGNORECASE)
                    if match_href:
                        toc_hrefs.append(match_href.group(1))

        # 1. 过滤掉所有原有的 CSS item 声明
        # 兼容 <item ... /> 和 <item ...></item>
        content = re.sub(r'<item\s+[^>]*media-type=["\']text/css["\'][^>]*/>', '', content)
        content = re.sub(r'<item\s+[^>]*media-type=["\']text/css["\'][^>]*>\s*</item>', '', content)

        # 2. 在 </manifest> 标签前插入我们最新的全球样式表注册，以及自定义字体与图片注册
        new_items = f'  <item id="global_beautify_style" href="{css_filename}" media-type="text/css"/>\n'
        
        # 兼容单字体与多字体注册
        fonts_to_register = []
        if isinstance(custom_fonts, list):
            fonts_to_register = custom_fonts
        elif custom_font:
            fonts_to_register = [custom_font]

        for idx, font_name in enumerate(fonts_to_register):
            font_format = "application/x-font-ttf"
            if font_name.lower().endswith(".otf"):
                font_format = "application/x-font-opentype"
            elif font_name.lower().endswith(".woff2"):
                font_format = "font/woff2"
            
            font_id = f"custom_font_{idx}" if len(fonts_to_register) > 1 else "custom_font"
            content = re.sub(rf'<item\s+[^>]*id=["\']{re.escape(font_id)}["\'][^>]*/>', '', content)
            new_items += f'  <item id="{font_id}" href="fonts/{font_name}" media-type="{font_format}"/>\n'

        if isinstance(custom_images, list):
            for idx, img_name in enumerate(custom_images):
                img_format = "image/png"
                if img_name.lower().endswith(".jpg") or img_name.lower().endswith(".jpeg"):
                    img_format = "image/jpeg"
                elif img_name.lower().endswith(".svg"):
                    img_format = "image/svg+xml"
                elif img_name.lower().endswith(".gif"):
                    img_format = "image/gif"
                    
                img_id = f"custom_img_{idx}"
                content = re.sub(rf'<item\s+[^>]*id=["\']{re.escape(img_id)}["\'][^>]*/>', '', content)
                new_items += f'  <item id="{img_id}" href="Images/{img_name}" media-type="{img_format}"/>\n'

        if "</manifest>" in content:
            content = content.replace("</manifest>", f"{new_items}</manifest>")
        else:
            content = re.sub(r'(</package>)', f'<manifest>\n{new_items}</manifest>\n\\1', content)

        # 4. 为全书所有包含弹注的 HTML item 自动注入 properties="footnote" 属性 (多看弹注关键引擎开关)
        opf_dir = os.path.dirname(opf_path)
        item_tags = re.findall(r'<item\s+[^>]*href=["\'][^"\']*\.(?:html|xhtml)["\'][^>]*>', content, re.IGNORECASE)
        for full_item_tag in set(item_tags):
            href_m = re.search(r'href=["\'](.*?)["\']', full_item_tag, re.IGNORECASE)
            if href_m:
                html_rel = href_m.group(1)
                html_abs = os.path.normpath(os.path.join(opf_dir, html_rel))
                if os.path.exists(html_abs):
                    try:
                        with open(html_abs, "r", encoding="utf-8", errors="ignore") as f:
                            h_str = f.read()
                        if "noteref" in h_str or "footnote" in h_str or "duokan-footnote" in h_str:
                            if "properties=" not in full_item_tag:
                                new_item_tag = full_item_tag.rstrip(">").rstrip("/") + ' properties="footnote"/>'
                                content = content.replace(full_item_tag, new_item_tag)
                            elif "footnote" not in full_item_tag:
                                new_item_tag = re.sub(r'properties=["\'](.*?)["\']', r'properties="\1 footnote"', full_item_tag)
                                content = content.replace(full_item_tag, new_item_tag)
                    except Exception:
                        pass

        # 3. 仅从 spine 线性阅读流中彻底删除物理目录项以隐藏常规翻页，但在 manifest 中予以保留确保系统目录树合法正常渲染
        if toc_item_ids:
            for item_id in toc_item_ids:
                # 匹配并从 spine 节点中删除该 itemref 项
                pattern_spine = rf'<itemref\s+[^>]*idref=["\']{re.escape(item_id)}["\'][^>]*/>'
                content = re.sub(pattern_spine, '', content, flags=re.IGNORECASE)
                pattern_spine_no_slash = rf'<itemref\s+[^>]*idref=["\']{re.escape(item_id)}["\'][^>]*>'
                content = re.sub(pattern_spine_no_slash, '', content, flags=re.IGNORECASE)

        # 3.8 净化并注入 guide 元数据：将 guide 里指向物理目录的 reference 死链重定向到分册封面以防崩溃
        first_cover_href = None
        if redirect_map and toc_hrefs:
            for old_href, target_href in redirect_map.items():
                if not first_cover_href:
                    first_cover_href = target_href
                pattern_guide = rf'(<reference\s+[^>]*href=["\']){re.escape(old_href)}(["\'][^>]*/>)'
                content = re.sub(pattern_guide, rf'\g<1>{target_href}\g<2>', content, flags=re.IGNORECASE)
        
        # 强力声明整本书的封面 HTML 章节 (以第一个重定向封面为准)
        if first_cover_href and "<guide>" in content:
            if 'type="cover"' not in content.lower() and "type='cover'" not in content.lower():
                cover_ref = f'\n        <reference type="cover" title="封面" href="{first_cover_href}" />'
                content = content.replace("<guide>", f"<guide>{cover_ref}")

        # 4. 生成全新的随机 UUID 并为标题追加 [精排版] 后缀，彻底击穿阅读器对同名/同UUID书籍的强力缓存机制
        import uuid
        new_uuid = f"urn:uuid:{uuid.uuid4()}"
        
        content = re.sub(
            r'(<dc:identifier[^>]*>)(.*?)(</dc:identifier>)', 
            rf'\g<1>{new_uuid}\g<3>', 
            content, 
            flags=re.IGNORECASE
        )
        
        def append_title_suffix(match):
            prefix = match.group(1)
            title = match.group(2)
            suffix = match.group(3)
            if "[精排版]" not in title:
                title = f"{title} [精排版]"
            return f"{prefix}{title}{suffix}"
            
        content = re.sub(
            r'(<dc:title[^>]*>)(.*?)(</dc:title>)', 
            append_title_suffix, 
            content, 
            flags=re.IGNORECASE
        )

        if ncx_path and os.path.exists(ncx_path):
            try:
                with open(ncx_path, "r", encoding="utf-8", errors="ignore") as f:
                    ncx_content = f.read()
                
                # 兼容不同的属性排列顺序，替换 ncx 中的 dtb:uid
                ncx_content = re.sub(
                    r'(<meta[^>]*name=["\']dtb:uid["\'][^>]*content=["\'])(.*?)(["\'][^>]*>)',
                    rf'\g<1>{new_uuid}\g<3>',
                    ncx_content,
                    flags=re.IGNORECASE
                )
                ncx_content = re.sub(
                    r'(<meta[^>]*content=["\'])(.*?)(["\'][^>]*name=["\']dtb:uid["\'][^>]*>)',
                    rf'\g<1>{new_uuid}\g<3>',
                    ncx_content,
                    flags=re.IGNORECASE
                )
                
                with open(ncx_path, "w", encoding="utf-8") as f:
                    f.write(ncx_content)
                print(f"[+] Synchronized NCX UUID success: {new_uuid}")

                # 4.5 终极物理剪除 NCX 系统目录树中指向已剔除物理目录的整个 navPoint 导航项目
                if toc_hrefs:
                    import xml.etree.ElementTree as ET
                    ET.register_namespace('', 'http://www.daisy.org/z3986/2005/ncx/')
                    
                    tree = ET.parse(ncx_path)
                    root = tree.getroot()
                    ns = {'ncx': 'http://www.daisy.org/z3986/2005/ncx/'}
                    
                    # 递归删除指向物理目录的整个 navPoint 节点
                    def prune_nav_points(parent):
                        children = parent.findall('ncx:navPoint', ns)
                        for child in children:
                            content_tag = child.find('ncx:content', ns)
                            if content_tag is not None:
                                src = content_tag.attrib.get('src', '')
                                src_file = src.split('#')[0]
                                if src_file in toc_hrefs:
                                    parent.remove(child)
                                    continue
                            # 递归深层嵌套
                            prune_nav_points(child)
                            
                    navmap = root.find('ncx:navMap', ns)
                    if navmap is not None:
                        prune_nav_points(navmap)
                    
                    tree.write(ncx_path, encoding='utf-8', xml_declaration=True)
                    print("[+] NCX Prune: successfully removed all directory navPoints from system menu!")
            except Exception as e:
                print(f"[-] Synchronize NCX UUID or NCX prune failed: {str(e)}")

        with open(opf_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _pack_epub(self, source_dir: str, output_epub: str):
        """
        将文件夹重新打包为 EPUB 电子书，遵守严格的 EPUB 打包规范
        """
        output_dir = os.path.dirname(output_epub)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with zipfile.ZipFile(output_epub, 'w', zipfile.ZIP_DEFLATED) as z:
            mimetype_path = os.path.join(source_dir, "mimetype")
            if os.path.exists(mimetype_path):
                z.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
            else:
                z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, source_dir)
                    if rel_path.replace('\\', '/') == "mimetype":
                        continue
                    z.write(full_path, rel_path)

    def _extract_original_css_rules(self, unzipped_dir: str) -> str:
        """
        扫描临时解压目录下的所有 CSS 文件，提取涉及自定义类名（如 kindle-cn 等）的排排版规则
        """
        import glob
        css_files = glob.glob(os.path.join(unzipped_dir, "**/*.css"), recursive=True)
        print(f"[*] CSS EXTRACT: found {len(css_files)} CSS files under {unzipped_dir}")
        retained_rules = []
        
        css_block_re = re.compile(r'([^{]+)\{([^}]+)\}', re.MULTILINE)
        
        for css_path in css_files:
            if "global_style.css" in os.path.basename(css_path):
                continue
            try:
                with open(css_path, "r", encoding="utf-8", errors="ignore") as f:
                    css_content = f.read()
                css_content = re.sub(r'/\*.*?\*/', '', css_content, flags=re.DOTALL)
                blocks = css_block_re.findall(css_content)
                for selector, rules_str in blocks:
                    selector = selector.strip()
                    if not ("." in selector or "#" in selector):
                        continue
                    sub_rules = []
                    rules = rules_str.split(";")
                    for r in rules:
                        r = r.strip()
                        if not r:
                            continue
                        r_lower = r.lower()
                        if any(x in r_lower for x in ["text-align", "font-weight", "font-style", "font-size", "text-indent"]) and not any(y in r_lower for y in ["margin", "padding", "line-height"]):
                            sub_rules.append(r)
                    if sub_rules:
                        rule_block = f"{selector} {{\n    " + ";\n    ".join(sub_rules) + ";\n}"
                        retained_rules.append(rule_block)
            except Exception as e:
                print(f"提取 CSS 失败 {css_path}: {e}")
                
        print(f"[*] CSS EXTRACT: compiled {len(retained_rules)} rules")
        return "\n\n".join(retained_rules)
