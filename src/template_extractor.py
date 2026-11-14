import os
import zipfile
import shutil
import re
import glob
from bs4 import BeautifulSoup
from src.epub_parser import EpubParser

class TemplateExtractor:
    def __init__(self):
        self.css_content = ""
        self.fonts = []  # 存放提取到的字体文件名
        self.images = [] # 存放提取到的图片资源文件名
        # 提取到的排版规则
        self.template_rules = {
            "align_center_classes": [],
            "align_right_classes": [],
            "no_indent_classes": [],
            "h1_classes": [],
            "h2_classes": [],
            "h3_classes": [],
            "p_classes": [],
            "custom_fonts_declared": [] # CSS 中声明的自定义字体名称
        }

    def extract_template(self, template_epub_path: str, temp_output_dir: str) -> dict:
        """
        解压并分析模板 EPUB 电子书，提取样式、字体和排版规则。
        
        :param template_epub_path: 模板 EPUB 的物理路径
        :param temp_output_dir: 临时工作目录，用于存放解压后的内容和生成的 template_style.css 等
        :return: 包含排版规则和字体信息的字典
        """
        # 1. 建立临时解压目录
        template_unzip_dir = os.path.join(temp_output_dir, "template_unzip")
        os.makedirs(template_unzip_dir, exist_ok=True)
        
        with zipfile.ZipFile(template_epub_path, 'r') as z:
            z.extractall(template_unzip_dir)

        # 2. 用 EpubParser 解析模板的结构，获取 OPF、HTML 和 CSS 的路径
        parser = EpubParser(template_epub_path)
        parser.open()
        
        opf_dir = os.path.dirname(os.path.join(template_unzip_dir, parser.opf_path))
        
        # 3. 收集并合并 CSS
        self._collect_and_merge_css(template_unzip_dir)
        
        # 4. 拷贝字体文件与弹注图标图片
        self._collect_fonts(template_unzip_dir, temp_output_dir)
        self._collect_images(template_unzip_dir, temp_output_dir)
        
        # 5. 分析 CSS 样式规则
        self._analyze_css_rules()
        
        # 6. 分析 HTML 结构特征（从前几章正文分析）
        self._analyze_html_structure(template_unzip_dir, parser.spine_paths)
        
        # 清理临时解压出来的所有原始模板文件以节省空间
        try:
            shutil.rmtree(template_unzip_dir)
        except Exception as e:
            print(f"[-] 清理模板临时解压目录失败: {e}")
            
        return {
            "rules": self.template_rules,
            "css_content": self.css_content,
            "fonts": self.fonts,
            "images": self.images
        }

    def _collect_and_merge_css(self, unzip_dir: str):
        """
        合并模板中所有的 CSS 样式文件，并重写其中的资源路径（如 url(...)）。
        """
        css_files = glob.glob(os.path.join(unzip_dir, "**/*.css"), recursive=True)
        merged_css = []
        
        for css_path in css_files:
            try:
                with open(css_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                
                # 清除 CSS 中的注释
                content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
                
                # 重写其中的 url 相对路径。电子书中的 url 通常指向字体或图片，例如 url(../fonts/font.ttf)
                # 我们统一将其重写为以 OPF 目录为基准的相对路径（global_style.css 与 fonts/ 目录同级，图片另说）
                # 匹配 url("...") 或 url('...') 或 url(...)
                def rewrite_url(match):
                    full_url = match.group(0)
                    url_path = match.group(1) or match.group(2) or match.group(3)
                    if not url_path:
                        return full_url
                    
                    # 剥离可能存在的查询参数或锚点
                    clean_path = url_path.split('?')[0].split('#')[0]
                    base_name = os.path.basename(clean_path)
                    
                    # 如果是字体文件，我们统一定位到 fonts/ 目录下
                    ext = os.path.splitext(base_name.lower())[1]
                    if ext in ['.ttf', '.otf', '.woff', '.woff2']:
                        return f'url("fonts/{base_name}")'
                    
                    # 其它资源（如图片分割线、背景）保留文件名或原样返回
                    return f'url("{base_name}")'

                # 匹配三种形式 of url(): 双引号、单引号、无引号
                content = re.sub(r'url\s*\(\s*["\'](.*?)["\']\s*\)|url\s*\(\s*\'(.*?)\'\s*\)|url\s*\(\s*([^"\'\s)]*)\s*\)', rewrite_url, content)
                
                merged_css.append(f"/* --- Merged from {os.path.basename(css_path)} --- */")
                merged_css.append(content)
            except Exception as e:
                print(f"[-] 读取并处理模板 CSS 失败 {css_path}: {e}")
                
        raw_css = "\n\n".join(merged_css)
        
        # 按照用户铁律：将所有文本 color 声明 100% 重置为纯黑 #000000，绝对保留边框 border 样式与花边
        processed_css = re.sub(r'color\s*:\s*[^;}]+[;]?', 'color: #000000;', raw_css)
        self.css_content = processed_css

    def _collect_fonts(self, unzip_dir: str, temp_output_dir: str):
        """
        查找并提取模板 EPUB 中的所有字体文件，拷贝到全局临时输出的 fonts 文件夹下。
        """
        font_extensions = ['*.ttf', '*.otf', '*.woff', '*.woff2']
        found_fonts = []
        
        for ext in font_extensions:
            found_fonts.extend(glob.glob(os.path.join(unzip_dir, f"**/{ext}"), recursive=True))
            # 兼容大小写
            found_fonts.extend(glob.glob(os.path.join(unzip_dir, f"**/{ext.upper()}"), recursive=True))
            
        # 去重
        found_fonts = list(set(found_fonts))
        
        if found_fonts:
            fonts_out_dir = os.path.join(temp_output_dir, "fonts")
            os.makedirs(fonts_out_dir, exist_ok=True)
            
            for font_path in found_fonts:
                base_name = os.path.basename(font_path)
                dest_path = os.path.join(fonts_out_dir, base_name)
                try:
                    shutil.copy2(font_path, dest_path)
                    self.fonts.append(base_name)
                    print(f"[+] 提取模板字体成功: {base_name}")
                except Exception as e:
                    print(f"[-] 拷贝模板字体失败 {base_name}: {e}")

    def _collect_images(self, unzip_dir: str, temp_output_dir: str):
        """
        查找并提取模板 EPUB 中的所有图片资源（如弹注小图标、分割线等），拷贝到临时 images 文件夹下。
        """
        img_extensions = ['*.png', '*.jpg', '*.jpeg', '*.svg', '*.gif']
        found_imgs = []
        
        for ext in img_extensions:
            found_imgs.extend(glob.glob(os.path.join(unzip_dir, f"**/{ext}"), recursive=True))
            found_imgs.extend(glob.glob(os.path.join(unzip_dir, f"**/{ext.upper()}"), recursive=True))
            
        found_imgs = list(set(found_imgs))
        if found_imgs:
            imgs_out_dir = os.path.join(temp_output_dir, "images")
            os.makedirs(imgs_out_dir, exist_ok=True)
            
            for img_path in found_imgs:
                base_name = os.path.basename(img_path)
                # 严禁拷贝封面和巨大大图，只允许收集真正的小弹注图标，彻底防止原书图片被样板封面污染
                if "cover" in base_name.lower() or "illust" in base_name.lower() or os.path.getsize(img_path) > 150 * 1024:
                    continue
                if not any(k in base_name.lower() for k in ["note", "footnote", "mark", "icon", "slim", "xian"]):
                    continue

                dest_path = os.path.join(imgs_out_dir, base_name)
                try:
                    shutil.copy2(img_path, dest_path)
                    self.images.append(base_name)
                    print(f"[+] 提取模板弹注图标成功: {base_name}")
                except Exception as e:
                    print(f"[-] 拷贝模板弹注图标失败 {base_name}: {e}")

    def _analyze_css_rules(self):
        """
        解析合并后的 CSS，识别出具有特定排版效果（如居中、居右、不缩进等）的类名。
        """
        if not self.css_content:
            return
            
        css_block_re = re.compile(r'([^{]+)\{([^}]+)\}', re.MULTILINE)
        blocks = css_block_re.findall(self.css_content)
        
        for selector_str, rules_str in blocks:
            # 拆分逗号选择器
            selectors = [s.strip() for s in selector_str.split(",") if s.strip()]
            rules = [r.strip() for r in rules_str.split(";") if r.strip()]
            
            # 解析该规则块的属性
            has_align_center = False
            has_align_right = False
            has_no_indent = False
            
            for r in rules:
                parts = r.split(":")
                if len(parts) < 2:
                    continue
                name = parts[0].strip().lower()
                val = "".join(parts[1:]).strip().lower()
                
                # 检查对齐
                if name == "text-align":
                    if "center" in val:
                        has_align_center = True
                    elif "right" in val:
                        has_align_right = True
                        
                # 检查缩进
                elif name == "text-indent":
                    # text-indent: 0, text-indent: 0em, text-indent: 0px 等
                    if val == "0" or "0em" in val or "0px" in val or "none" in val:
                        has_no_indent = True
                        
                # 收集 CSS 声明的字体，如果是自定义的字体
                elif name == "font-family":
                    # 记录声明过的字体，如果是用双引号包裹的
                    matches = re.findall(r'["\']([^"\']+)["\']', val)
                    for m in matches:
                        if m not in self.template_rules["custom_fonts_declared"]:
                            self.template_rules["custom_fonts_declared"].append(m)

            # 将检测到的排版类名收集起来
            for sel in selectors:
                # 我们只关心类选择器，如 .center, p.no-indent 等
                class_matches = re.findall(r'\.([a-zA-Z0-9_-]+)', sel)
                for cls in class_matches:
                    if has_align_center and cls not in self.template_rules["align_center_classes"]:
                        self.template_rules["align_center_classes"].append(cls)
                    if has_align_right and cls not in self.template_rules["align_right_classes"]:
                        self.template_rules["align_right_classes"].append(cls)
                    if has_no_indent and cls not in self.template_rules["no_indent_classes"]:
                        self.template_rules["no_indent_classes"].append(cls)

    def _analyze_html_structure(self, unzip_dir: str, spine_paths: list):
        """
        通过分析模板电子书中的 HTML 章节，统计各重要排版元素（标题、正文段落）的 class 分布。
        
        :param unzip_dir: 模板解压目录
        :param spine_paths: 书籍章节相对路径列表
        """
        # 只挑前几章正文分析，避免全书扫描降低性能
        sample_paths = [p for p in spine_paths if not any(x in p.lower() for x in ['cover', 'toc', 'nav', 'author', 'title'])]
        sample_paths = sample_paths[:5] if sample_paths else spine_paths[:3]
        
        h1_classes_count = {}
        h2_classes_count = {}
        h3_classes_count = {}
        p_classes_count = {}
        
        for rel_path in sample_paths:
            full_path = os.path.join(unzip_dir, rel_path)
            if not os.path.exists(full_path):
                continue
                
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    html_content = f.read()
                    
                # 剔除命名实体避免 XML 报错，简单使用 BeautifulSoup 解析
                import html
                soup = BeautifulSoup(html.unescape(html_content), "xml")
                
                # 统计 h1-h3 的 class
                for h1 in soup.find_all("h1"):
                    cls_list = h1.get("class", [])
                    cls_list = [cls_list] if not isinstance(cls_list, list) else cls_list
                    for cls in cls_list:
                        h1_classes_count[cls] = h1_classes_count.get(cls, 0) + 1
                        
                for h2 in soup.find_all("h2"):
                    cls_list = h2.get("class", [])
                    cls_list = [cls_list] if not isinstance(cls_list, list) else cls_list
                    for cls in cls_list:
                        h2_classes_count[cls] = h2_classes_count.get(cls, 0) + 1
                        
                for h3 in soup.find_all("h3"):
                    cls_list = h3.get("class", [])
                    cls_list = [cls_list] if not isinstance(cls_list, list) else cls_list
                    for cls in cls_list:
                        h3_classes_count[cls] = h3_classes_count.get(cls, 0) + 1
                        
                # 统计正文 p 的 class
                for p in soup.find_all("p"):
                    cls_list = p.get("class", [])
                    cls_list = [cls_list] if not isinstance(cls_list, list) else cls_list
                    for cls in cls_list:
                        # 过滤掉空的 class 属性
                        if cls:
                            p_classes_count[cls] = p_classes_count.get(cls, 0) + 1
                            
            except Exception as e:
                print(f"[-] 分析模板 HTML 失败 {rel_path}: {e}")
                
        # 整理高频出现的 class
        # 选取频次最高的 class 放入规则字典中
        def get_top_classes(counter_dict, threshold=2):
            sorted_classes = sorted(counter_dict.items(), key=lambda x: x[1], reverse=True)
            return [cls for cls, count in sorted_classes if count >= threshold and cls]

        self.template_rules["h1_classes"] = get_top_classes(h1_classes_count)
        self.template_rules["h2_classes"] = get_top_classes(h2_classes_count)
        self.template_rules["h3_classes"] = get_top_classes(h3_classes_count)
        self.template_rules["p_classes"] = get_top_classes(p_classes_count, threshold=5)
