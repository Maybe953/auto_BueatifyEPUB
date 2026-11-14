import re
import os
from bs4 import BeautifulSoup
import zhconv
from src.config import BeautifyConfig
from src.css_builder import build_beautified_css

# 常见标题正则表达式
CHAPTER_RE = re.compile(
    r'^\s*(第[零一二三四五六七八九十百千万\d]+[章回卷集期幕说折]|[Cc]hapter\s+\d+|[Cc]HAPTER\s+[IVXLCDM\d]+)\s*.*$',
    re.IGNORECASE
)

class HtmlCleaner:
    def __init__(self, config: BeautifyConfig):
        self.config = config

    def clean_html(self, html_content: str, css_rel_path: str = "global_style.css", current_html_path: str = None, redirect_map: dict = None) -> str:
        """
        对单个 XHTML/HTML 文件的内容进行核心精排清洗。
        
        :param html_content: 原始的 HTML 字符串
        :param css_rel_path: 新的全局样式表相对于当前 HTML 文件的路径
        :param current_html_path: 当前 HTML 文件相对于 zip 包的相对路径 (如 OEBPS/text/volume1/chapter01.xhtml)
        :param redirect_map: 已剔除的物理目录与其重定向目标的映射字典
        """
        # 将 HTML 命名字符实体（如 &ldquo;, &mdash;, &nbsp; 等）一律转为真实 Unicode 汉字及标点，防止 XML 引擎在解析未定义实体时报错崩溃
        import html
        html_content = html.unescape(html_content)

        # 如果需要简繁转换，在解析前对整个文本执行简繁体转换（效率最高）
        if self.config.convert_to_simplified:
            html_content = zhconv.convert(html_content, 'zh-cn')
            # 优化简体排版：将直角括号转为简体弯引号
            html_content = html_content.replace('「', '“').replace('」', '”')
            html_content = html_content.replace('『', '‘').replace('』', '’')

        # 使用 XML 解析器以确保输出严格的 XHTML 闭合规范，极其有利于 Kindle 兼容性
        soup = BeautifulSoup(html_content, "xml")

        # 1. 替换或删除原书所有的 CSS 样式表链接 (不限大小写，凡是以 .css 结尾的链接均彻底清除)
        for link in list(soup.find_all("link")):
            href_val = link.get("href", "").lower()
            if ".css" in href_val:
                link.decompose()
        for style_tag in list(soup.find_all("style")):
            style_tag.decompose()

        # 2. 插入我们全新构建的标准精排 CSS 链接
        head = soup.find("head")
        if not head:
            # 如果原书奇葩地没有 head 标签，则新建一个
            head = soup.new_tag("head")
            if soup.html:
                soup.html.insert(0, head)
            else:
                # 连 html 标签都没有，则直接在最外层创建一个
                html_tag = soup.new_tag("html")
                soup.append(html_tag)
                html_tag.append(head)
                
        # 加上通用字符集声明
        meta_charset = soup.new_tag("meta", charset="utf-8")
        head.append(meta_charset)
        
        # 链接我们的外部 global_style.css (以保持与原书提取出的加粗、对齐等样式的继承)
        new_css_link = soup.new_tag("link", rel="stylesheet", href=css_rel_path, type="text/css")
        head.append(new_css_link)
        
        # 内联注入核心精排样式表，彻底突破一切相对路径寻址解析故障与阅读器的排版拦截偏见
        # 发烧友级优化：动态推导字体相对于当前 HTML 所在的目录深度，重写 @font-face 寻址以支持多级子目录章节
        rel_font_url = None
        if self.config.custom_font:
            rel_opf_dir = os.path.dirname(css_rel_path)
            if rel_opf_dir:
                rel_font_url = os.path.join(rel_opf_dir, f"fonts/{self.config.custom_font}").replace('\\', '/')
            else:
                rel_font_url = f"fonts/{self.config.custom_font}"
                
        core_css = build_beautified_css(self.config, is_preview=False, custom_font_url=rel_font_url)
        inline_style_tag = soup.new_tag("style", type="text/css")
        inline_style_tag.string = f"/*<![CDATA[*/\n{core_css}\n/*]]>*/"
        head.append(inline_style_tag)

        # 3. 剥离无语义的 div 和 span 嵌套并清理行内样式
        body = soup.find("body")
        if not body:
            # 兼容：如果不存在 body，则将整个 soup 作为主体
            body = soup

        # 递归清洗行内样式与排版对齐属性
        for tag in list(body.find_all(True)):
            # 特意提取标题（h1-h6）、段落或容器中可能的原对齐属性，以保留原书意图
            alignment_class = None
            if tag.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div']:
                # 1. 检查 align 属性
                align_val = tag.get('align', '').lower() if tag.has_attr('align') else ''
                
                # 2. 检查 style 中的 text-align 属性
                style_val = tag.get('style', '') if tag.has_attr('style') else ''
                if not align_val and style_val:
                    style_align = re.search(r'text-align\s*:\s*(center|left|right)', style_val, re.IGNORECASE)
                    if style_align:
                        align_val = style_align.group(1).lower()
                        
                # 3. 检查原有 class 列表中是否含有暗示对齐的关键词 (兼容原书样式定义)
                if not align_val:
                    classes = tag.get('class', [])
                    if not isinstance(classes, list):
                        classes = [classes]
                    for cls_name in classes:
                        cls_lower = str(cls_name).lower()
                        # 将连字符与下划线替换为空格并分词，防止 copyright 误匹配为 right
                        cls_words = cls_lower.replace('-', ' ').replace('_', ' ').split()
                        if 'right' in cls_words:
                            align_val = 'right'
                            break
                        elif 'center' in cls_words or 'middle' in cls_words:
                            align_val = 'center'
                            break
                        elif 'left' in cls_words:
                            align_val = 'left'
                            break
                        
                if align_val in ['center', 'left', 'right']:
                    alignment_class = f"align-{align_val}"

            # 如果开启了行内样式清洗，剥离行内样式与旧版属性
            if self.config.clean_inline_styles:
                if tag.has_attr('style'):
                    del tag['style']
                
                # 保留矢量图(svg, image)、数学公式(math)、画布(canvas)及媒体容器等核心宽高属性
                attrs_to_del = ['align', 'bgcolor', 'border', 'valign', 'cellspacing', 'cellpadding']
                if tag.name not in ["svg", "image", "math", "canvas", "video", "iframe"]:
                    attrs_to_del.extend(['width', 'height'])
                    
                for attr in attrs_to_del:
                    if tag.has_attr(attr):
                        del tag[attr]
            else:
                # 哪怕未开启行内清洗，也应去掉干扰对齐的 align 属性，交给 class 统一控制
                if tag.has_attr('align'):
                    del tag['align']
                    
            # 将检测到的对齐方向以高优 class 方式重新赋加
            if alignment_class:
                classes = tag.get('class', [])
                if not isinstance(classes, list):
                    classes = [classes]
                if alignment_class not in classes:
                    classes.append(alignment_class)
                    tag['class'] = classes

        # 剥离冗余的 span 嵌套 (仅保留内容，使用 list 保证安全)
        if self.config.clean_spans:
            for span in list(body.find_all("span")):
                # 如果 span 没有 class，或者 class 看起来是无用的随机样式，可以直接剥离
                # 只有当 span 包含特定功能如 "footnote" 时保留
                cls = span.get("class", [])
                if not isinstance(cls, list):
                    cls = [cls]
                # 对大多数没有重要修饰的 span 进行平铺
                if not any(c in ["footnote", "note", "pinyin"] for c in cls):
                    span.unwrap()

        # 清除无语义 of div 并将其展平或转换为标准容器 (使用 list 保证安全)
        if self.config.clean_divs:
            for div in list(body.find_all("div")):
                cls = div.get("class", [])
                if not isinstance(cls, list):
                    cls = [cls]
                
                # 如果是图片容器等，保留结构但去除无用属性
                if any(c in ["image", "img", "figure", "illustration"] for c in cls):
                    div["class"] = "img-container"
                else:
                    # 如果 div 包含 svg、table、iframe 等块级重要结构，保留容器以防排版崩坏
                    has_special_child = any(div.find(x) for x in ["svg", "table", "iframe", "math"])
                    if has_special_child:
                        if div.find("svg") or div.find("img"):
                            # 识别是否是全屏封面容器：如果页面 title 是 Cover 或者是 封面，赋予封面专用容器类名
                            html_title = soup.find("title")
                            title_text = html_title.get_text().lower() if html_title else ""
                            if "cover" in title_text or "封面" in title_text:
                                div["class"] = "cover-container"
                            else:
                                div["class"] = "img-container"
                        else:
                            div["class"] = "table-container"
                    else:
                        # 其它普通 div 予以解包，将正文直接展出
                        div.unwrap()

        # 4. 精细化清理段落 `<p>` 与空行 (使用 list 保证安全)
        for p in list(body.find_all("p")):
            text = p.get_text().strip()
            
            # 清理空行
            if self.config.remove_empty_paragraphs:
                # 判断段落是否完全为空，或者只包含 br、&nbsp; 或空白符
                is_empty = False
                if not text:
                    is_empty = True
                elif text == "\u00a0" or text == "&nbsp;":
                    is_empty = True
                
                # 特殊情况：如果段落里有图片，绝不能删
                if p.find("img"):
                    is_empty = False
                    
                if is_empty:
                    p.decompose()
                    continue

            # 5. 标题智能提取与规范化（仅在开启选项时执行，避免强行改变段落标签结构）
            if self.config.auto_detect_titles:
                cls = p.get("class", [])
                if not isinstance(cls, list):
                    cls = [cls]
                    
                is_title = False
                # 规则 A：文本符合章节正则表达式
                if CHAPTER_RE.match(text) and len(text) < 50:
                    is_title = True
                # 规则 B：类名符合标题暗示
                elif any(c in ["chapter", "title", "heading", "h1", "h2"] for c in cls) and len(text) < 80:
                    is_title = True
                    
                if is_title:
                    # 将 <p> 标签转换为 <h2> 标签，促成自动分页与目录索引
                    p.name = "h2"

        # 处理原本已存在的 h 标签，确保它们干净无内联样式 (使用 list 保证安全)
        for h_tag in list(body.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])):
            # 不再删除已有 h 标签的 class，以保留原书及提取得到的样式规则对齐 (如居左、加粗等)
            pass

        # 6. 处理图片自适应与容器 (使用 list 保证安全)
        for img in list(body.find_all("img")):
            # 确保图片有 alt 属性
            if not img.has_attr("alt"):
                img["alt"] = "image"
            
            # 仅在启用 wrap_images 选项时才对图片标签的父级容器进行改写或重新包裹
            if self.config.wrap_images:
                parent = img.parent
                if parent and parent.name in ["p", "div"]:
                    parent["class"] = "img-container"
                else:
                    # 如果没有容器包裹，主动为其建立一个 img-container 的段落包裹
                    wrapper = soup.new_tag("p", attrs={"class": "img-container"})
                    img.replace_with(wrapper)
                    wrapper.append(img)

        # 6.5 发烧友级优化：重定向指向已删除物理目录的超链接，确保正文内的跳转完好无损
        if redirect_map and current_html_path:
            html_dir = os.path.dirname(current_html_path)
            for a in soup.find_all("a"):
                href = a.get("href", "")
                if href:
                    parts = href.split("#")
                    href_file = parts[0]
                    anchor = f"#{parts[1]}" if len(parts) > 1 else ""
                    
                    if not href_file:
                        continue
                        
                    # 计算链接目标的绝对相对路径
                    target_abs = os.path.normpath(os.path.join(html_dir, href_file)).replace('\\', '/')
                    if target_abs in redirect_map:
                        new_target_abs = redirect_map[target_abs]
                        # 计算相对于当前 HTML 所在的目录的相对跳转路径
                        rel_new_target = os.path.relpath(new_target_abs, html_dir).replace('\\', '/')
                        a["href"] = f"{rel_new_target}{anchor}"

        # 7. 保证 XML/XHTML 严格的命名空间与文档声明，Kindle 强依赖此规范
        html_node = soup.find("html")
        if html_node:
            html_node["xmlns"] = "http://www.w3.org/1999/xhtml"
            html_node["xmlns:epub"] = "http://www.idpf.org/2007/ops"
            if self.config.convert_to_simplified:
                html_node["xml:lang"] = "zh-CN"
                html_node["lang"] = "zh-CN"

        # 转换为字符串并返回。'xml' 解析器输出的是标准的严格 XML 格式，完美闭合所有标签。
        html_str = str(soup)

        # 8. 修复 BeautifulSoup 在 xml 模式下把非 void 标签序列化为自闭合（如 <title/>, <div/>）
        # 导致前端 HTML5 浏览器加载 srcdoc 页面时解析错误进而白屏的问题
        non_void_tags = [
            'title', 'div', 'span', 'p', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 
            'script', 'style', 'iframe', 'blockquote', 'ul', 'ol', 'li', 'head', 'body'
        ]
        for tag in non_void_tags:
            pattern = rf'<{tag}(\s+[^>]*?)?\s*/>'
            html_str = re.sub(pattern, rf'<{tag}\1></{tag}>', html_str, flags=re.IGNORECASE)

        return html_str

    def clean_html_with_template(self, html_content: str, css_rel_path: str, template_rules: dict, inline_css_content: str = None, current_html_path: str = None, redirect_map: dict = None) -> str:
        """
        基于模板 EPUB 排版特征和 CSS，对单个 HTML/XHTML 进行语义化清洗与适配。
        """
        import html
        html_content = html.unescape(html_content)

        if self.config.convert_to_simplified:
            html_content = zhconv.convert(html_content, 'zh-cn')
            html_content = html_content.replace('「', '“').replace('」', '”')
            html_content = html_content.replace('『', '‘').replace('』', '’')

        soup = BeautifulSoup(html_content, "xml")

        # 1. 移除旧的 CSS 引用
        for link in list(soup.find_all("link")):
            href_val = link.get("href", "").lower()
            if ".css" in href_val:
                link.decompose()
        for style_tag in list(soup.find_all("style")):
            style_tag.decompose()

        # 2. 注入模板 CSS
        head = soup.find("head")
        if not head:
            head = soup.new_tag("head")
            if soup.html:
                soup.html.insert(0, head)
            else:
                html_tag = soup.new_tag("html")
                soup.append(html_tag)
                html_tag.append(head)

        meta_charset = soup.new_tag("meta", charset="utf-8")
        head.append(meta_charset)

        new_css_link = soup.new_tag("link", rel="stylesheet", href=css_rel_path, type="text/css")
        head.append(new_css_link)

        # 注入首行缩进保护、大章节强制分页、样式黑字重置与封面全屏无边距充满规则
        cover_protect_style = soup.new_tag("style", type="text/css")
        cover_protect_style.string = (
            "/*<![CDATA[*/\n"
            "@page { margin: 0; }\n"
            "html, body { height: 100%; margin: 0; padding: 0; text-align: justify; text-justify: inter-ideograph; word-break: break-all; }\n"
            "h1, h2, h3, h4, h5, h6, p, blockquote, div { color: #000000 !important; }\n"
            "h1 { font-size: 1.3em !important; font-weight: normal !important; line-height: 1.7 !important; text-align: center !important; margin: 3.2em 0 2em 0 !important; }\n"
            "h2 { font-size: 1.12em !important; font-weight: normal !important; line-height: 1.3 !important; text-align: left !important; margin: 2.2em 0 1.8em 0 !important; }\n"
            "h3 { font-size: 1.05em !important; font-weight: normal !important; line-height: 1.3 !important; text-align: left !important; margin: 2.2em 0 1.8em 0 !important; }\n"
            "h1, h2, .h1, .h2 { page-break-before: always !important; break-before: page !important; }\n"
            "body > h1:first-child, body > h2:first-child { page-break-before: avoid !important; break-before: avoid !important; }\n"
            "p { text-indent: 2em; margin: 1em 0; line-height: 1.6em; text-align: justify; }\n"
            "p.center, p.right, p.cover, p.image, p.footnote, h1, h2, h3, h4, h5, h6 { text-indent: 0 !important; }\n"
            ".h1kt { border-top: 1px #3a7075 solid; border-bottom: 1px #3a7075 solid; padding: 0.25em 0; margin: 0.5em 0; }\n"
            ".cover, .cover-container { width: 100%; height: 100vh; margin: 0; padding: 0; text-align: center; display: flex; justify-content: center; align-items: center; }\n"
            ".cover img, .cover-container img { max-width: 100%; max-height: 100vh; object-fit: contain; margin: 0 auto; display: block; }\n"
            "/*]]>*/"
        )
        head.append(cover_protect_style)

        # 如果提供了模板的完整 CSS，也可以内联注入
        if inline_css_content:
            inline_style_tag = soup.new_tag("style", type="text/css")
            inline_style_tag.string = f"/*<![CDATA[*/\n{inline_css_content}\n/*]]>*/"
            head.append(inline_style_tag)

        # 收集模板定义的有效 class 集合，便于快速匹配
        template_classes = set(
            template_rules.get("align_center_classes", []) +
            template_rules.get("align_right_classes", []) +
            template_rules.get("no_indent_classes", []) +
            template_rules.get("h1_classes", []) +
            template_rules.get("h2_classes", []) +
            template_rules.get("h3_classes", []) +
            template_rules.get("p_classes", [])
        )

        body = soup.find("body") or soup

        # 3. 递归分析与清洗所有元素
        for tag in list(body.find_all(True)):
            # 3.1 识别对齐特征
            alignment = None
            if tag.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div']:
                align_val = tag.get('align', '').lower() if tag.has_attr('align') else ''
                style_val = tag.get('style', '') if tag.has_attr('style') else ''
                if not align_val and style_val:
                    style_align = re.search(r'text-align\s*:\s*(center|left|right)', style_val, re.IGNORECASE)
                    if style_align:
                        align_val = style_align.group(1).lower()
                
                # 如果没有明显的属性，看看它原有的 class 里是否含有对齐类名
                if not align_val:
                    classes = tag.get('class', [])
                    if not isinstance(classes, list):
                        classes = [classes]
                    for cls_name in classes:
                        cls_str = str(cls_name).lower()
                        if cls_str in template_rules.get("align_center_classes", []):
                            alignment = "center"
                            break
                        elif cls_str in template_rules.get("align_right_classes", []):
                            alignment = "right"
                            break
                        # 兼容通用的对齐词
                        cls_words = cls_str.replace('-', ' ').replace('_', ' ').split()
                        if 'center' in cls_words or 'middle' in cls_words:
                            alignment = "center"
                            break
                        elif 'right' in cls_words:
                            alignment = "right"
                            break
                else:
                    alignment = align_val

            # 3.2 过滤行内样式 (在模板精排模式下一律强制全量剔除内联 style，防止覆盖模板 CSS)
            if tag.has_attr('style'):
                del tag['style']
            attrs_to_del = ['align', 'bgcolor', 'border', 'valign', 'cellspacing', 'cellpadding']
            if tag.name not in ["svg", "image", "math", "canvas", "video", "iframe"]:
                attrs_to_del.extend(['width', 'height'])
            for attr in attrs_to_del:
                if tag.has_attr(attr):
                    del tag[attr]

            # 3.3 类名过滤与高保真语义映射
            orig_classes = tag.get('class', [])
            if not isinstance(orig_classes, list):
                orig_classes = [orig_classes]
            
            new_classes = []
            # 定义可能破坏首行缩进的特殊类名白名单
            no_indent_specials = {"bookname", "vol", "cp", "cp1", "h1", "h2", "h3", "title", "cover"}

            # 规则一：保留原有的类名，但对于普通 p 标签，排除破坏缩进的特殊类名
            for c in orig_classes:
                if tag.name == 'p' and c in no_indent_specials:
                    continue
                if c in template_classes or c in ["center", "right", "kh", "fs", "kt", "xian", "cover", "image"]:
                    new_classes.append(c)

            # 智能判断是否为小标题 (例如 "一 平民家世", "二 出生的神话")
            if tag.name == 'p':
                text_content = tag.get_text().strip()
                if 0 < len(text_content) <= 40:
                    # 正则表达匹配：开头包含中文数字/罗马数字/阿拉伯数字加空格或点
                    if re.match(r'^(?:[一二三四五六七八九十]+\s+|第[一二三四五六七八九十0-9]+[章节条]?|\d+[\.\s]+).*$', text_content):
                        tag.name = 'h3'

            # 规则二：对特定语义标签（标题、正文、引用、对齐）注入模板所对应的标准类名
            if tag.name == 'h1':
                new_classes.extend(["h1", "h1kt"])
            elif tag.name == 'h2':
                new_classes.extend(["h2", "kt"])
            elif tag.name == 'h3':
                new_classes.extend(["h3", "kt"])
            elif tag.name == 'blockquote':
                for bq_p in tag.find_all('p'):
                    bq_classes = bq_p.get('class', [])
                    if not isinstance(bq_classes, list):
                        bq_classes = [bq_classes]
                    if 'fs' not in bq_classes:
                        bq_classes.append('fs')
                    bq_p['class'] = bq_classes
            elif tag.name == 'p':
                # 检查对齐或缩进特征
                if alignment == 'center':
                    new_classes.append("center")
                elif alignment == 'right':
                    new_classes.append("right")
            
            # 去重并更新 class 属性
            if new_classes:
                tag['class'] = list(set(new_classes))
            else:
                if tag.has_attr('class'):
                    del tag['class']

        # 4. 封面 (Cover) 全屏无边距满页自适应适配
        is_cover_page = (current_html_path and "cover" in current_html_path.lower()) or body.find("div", class_="cover") or body.find(class_=lambda x: x and "cover" in str(x).lower())
        if is_cover_page:
            imgs = body.find_all("img")
            for img in imgs:
                img["style"] = "max-width:100%;max-height:100vh;object-fit:contain;margin:0 auto;display:block;"
            cover_div = body.find("div", class_="cover") or body.find("div")
            if cover_div:
                cover_div["class"] = "cover"
                cover_div["style"] = "width:100%;height:100vh;margin:0;padding:0;display:flex;justify-content:center;align-items:center;"

        # 5. span 和 div 的剥离（同时高度保护 ID/NAME 跳转锚点）
        if self.config.clean_spans:
            for span in list(body.find_all("span")):
                if span.has_attr("id") or span.has_attr("name"):
                    anchor_id = span.get("id") or span.get("name")
                    parent = span.parent
                    if parent and not parent.has_attr("id"):
                        parent["id"] = anchor_id
                
                cls = span.get("class", [])
                cls = [cls] if not isinstance(cls, list) else cls
                if not any(c in template_classes for c in cls) and not any(c in ["footnote", "note", "koboSpan"] for c in cls):
                    if not (span.has_attr("id") or span.has_attr("name")):
                        span.unwrap()

        if self.config.clean_divs:
            for div in list(body.find_all("div")):
                cls = div.get("class", [])
                cls = [cls] if not isinstance(cls, list) else cls
                
                if any(c in ["image", "img", "figure", "illustration"] for c in cls):
                    div["class"] = "img-container"
                elif any(c in template_classes for c in cls):
                    pass
                else:
                    has_special_child = any(div.find(x) for x in ["svg", "table", "iframe", "math"])
                    if has_special_child:
                        div["class"] = "img-container" if (div.find("svg") or div.find("img")) else "table-container"
                    else:
                        div.unwrap()

        # 5. 空行和标题智能处理
        for p in list(body.find_all("p")):
            text = p.get_text().strip()
            if self.config.remove_empty_paragraphs:
                is_empty = not text or text == "\u00a0" or text == "&nbsp;"
                if is_empty and not p.find("img"):
                    p.decompose()
                    continue

            if self.config.auto_detect_titles:
                cls = p.get("class", [])
                cls = [cls] if not isinstance(cls, list) else cls
                is_title = False
                if CHAPTER_RE.match(text) and len(text) < 50:
                    is_title = True
                elif any(c in ["chapter", "title", "heading", "h1", "h2"] for c in cls) and len(text) < 80:
                    is_title = True
                    
                if is_title:
                    p.name = "h2"
                    if template_rules.get("h2_classes"):
                        p["class"] = [template_rules["h2_classes"][0]]

        # 6. 处理图片自适应与容器
        for img in list(body.find_all("img")):
            if not img.has_attr("alt"):
                img["alt"] = "image"
            if self.config.wrap_images:
                parent = img.parent
                if parent and parent.name in ["p", "div"]:
                    parent["class"] = "img-container"
                else:
                    wrapper = soup.new_tag("p", attrs={"class": "img-container"})
                    img.replace_with(wrapper)
                    wrapper.append(img)

        # 7. 重定向超链接
        if redirect_map and current_html_path:
            html_dir = os.path.dirname(current_html_path)
            for a in soup.find_all("a"):
                href = a.get("href", "")
                if href:
                    parts = href.split("#")
                    href_file = parts[0]
                    anchor = f"#{parts[1]}" if len(parts) > 1 else ""
                    if href_file:
                        target_abs = os.path.normpath(os.path.join(html_dir, href_file)).replace('\\', '/')
                        if target_abs in redirect_map:
                            new_target_abs = redirect_map[target_abs]
                            rel_new_target = os.path.relpath(new_target_abs, html_dir).replace('\\', '/')
                            a["href"] = f"{rel_new_target}{anchor}"

        # 8. 规范化命名空间
        html_node = soup.find("html")
        if html_node:
            html_node["xmlns"] = "http://www.w3.org/1999/xhtml"
            html_node["xmlns:epub"] = "http://www.idpf.org/2007/ops"
            if self.config.convert_to_simplified:
                html_node["xml:lang"] = "zh-CN"
                html_node["lang"] = "zh-CN"

        html_str = str(soup)

        non_void_tags = [
            'title', 'div', 'span', 'p', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 
            'script', 'style', 'iframe', 'blockquote', 'ul', 'ol', 'li', 'head', 'body'
        ]
        for tag in non_void_tags:
            pattern = rf'<{tag}(\s+[^>]*?)?\s*/>'
            html_str = re.sub(pattern, rf'<{tag}\1></{tag}>', html_str, flags=re.IGNORECASE)

        return html_str
