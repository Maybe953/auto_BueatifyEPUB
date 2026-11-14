import zipfile
import xml.etree.ElementTree as ET
import os

class EpubParser:
    def __init__(self, epub_path):
        self.epub_path = epub_path
        self.zip_ref = None
        self.opf_path = ""
        self.opf_dir = ""
        self.metadata = {}
        self.manifest = {}  # id -> {href, media_type}
        self.spine = []     # list of itemref idrefs
        self.spine_paths = [] # list of zip relative paths to spine xhtml files
        self.original_spine_paths = [] # list of zip relative paths to all original spine items
        self.ncx_path = ""
        self.nav_path = ""
        
    def open(self):
        self.zip_ref = zipfile.ZipFile(self.epub_path, 'r')
        self._parse_container()
        self._parse_opf()
        
    def close(self):
        if self.zip_ref:
            self.zip_ref.close()
            
    def __enter__(self):
        self.open()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def read_file(self, rel_path):
        """读取 zip 内指定路径的文件内容 (返回 bytes)"""
        normalized_path = rel_path.replace('\\', '/')
        return self.zip_ref.read(normalized_path)

    def read_text_file(self, rel_path, encoding='utf-8'):
        """读取 zip 内指定路径的文件内容 (返回 str)"""
        content_bytes = self.read_file(rel_path)
        try:
            return content_bytes.decode(encoding)
        except UnicodeDecodeError:
            # 自动尝试其它编码
            return content_bytes.decode('gbk', errors='ignore')

    def _parse_container(self):
        """解析 META-INF/container.xml 找到 OPF 文件的路径"""
        try:
            container_xml = self.read_text_file("META-INF/container.xml")
            root = ET.fromstring(container_xml)
            # 处理 XML 命名空间
            ns = {'ns': 'urn:oasis:names:tc:opendocument:xmlns:container'}
            rootfile = root.find('.//ns:rootfile', ns)
            if rootfile is not None:
                self.opf_path = rootfile.attrib.get('full-path', '')
                self.opf_dir = os.path.dirname(self.opf_path)
            else:
                raise ValueError("EPUB 格式错误: container.xml 中未找到 rootfile")
        except Exception as e:
            raise ValueError(f"解析 container.xml 失败: {str(e)}")

    def _parse_opf(self):
        """解析 content.opf 获取书籍元数据、Manifest 和 Spine"""
        try:
            opf_content = self.read_text_file(self.opf_path)
            root = ET.fromstring(opf_content)
            
            # OPF 的命名空间
            # XML 可能会带有命名空间，例如 {http://www.idpf.org/2007/opf}package
            # 我们通过获取根节点的 tag 来提取命名空间前缀
            ns_prefix = ""
            if root.tag.startswith('{'):
                ns_prefix = root.tag.split('}')[0] + '}'
                
            ns = {
                'opf': ns_prefix.strip('{}') if ns_prefix else '',
                'dc': 'http://purl.org/dc/elements/1.1/'
            }
            
            # 1. 解析 Metadata
            metadata_node = root.find(f'.//{ns_prefix}metadata')
            if metadata_node is not None:
                # 获取标题
                title_node = metadata_node.find('.//dc:title', ns)
                self.metadata['title'] = title_node.text if title_node is not None else "未知书名"
                # 获取作者
                creator_node = metadata_node.find('.//dc:creator', ns)
                self.metadata['creator'] = creator_node.text if creator_node is not None else "未知作者"
                # 获取语言
                lang_node = metadata_node.find('.//dc:language', ns)
                self.metadata['language'] = lang_node.text if lang_node is not None else "zh"
            
            # 2. 解析 Manifest
            manifest_node = root.find(f'.//{ns_prefix}manifest')
            if manifest_node is not None:
                for item in manifest_node.findall(f'.//{ns_prefix}item'):
                    item_id = item.attrib.get('id', '')
                    href = item.attrib.get('href', '')
                    media_type = item.attrib.get('media-type', '')
                    properties = item.attrib.get('properties', '')
                    
                    self.manifest[item_id] = {
                        'href': href,
                        'media_type': media_type,
                        'properties': properties
                    }
                    
                    # 记录 TOC.NCX 路径
                    if media_type == 'application/x-dtbncx+xml':
                        self.ncx_path = self._resolve_path(href)
                    # 记录 EPUB 3 HTML NAV 路径
                    if 'nav' in properties.split():
                        self.nav_path = self._resolve_path(href)

            # 3. 解析 Guide (Epub 2 常见物理目录定义)
            # 提前解析 Guide，以便在解析 Spine 时能获取完整的物理目录路径进行过滤
            self.guide_toc_href = ""
            guide_node = root.find(f'.//{ns_prefix}guide')
            if guide_node is not None:
                for ref in guide_node.findall(f'.//{ns_prefix}reference'):
                    ref_type = ref.attrib.get('type', '')
                    if ref_type == 'toc':
                        self.guide_toc_href = ref.attrib.get('href', '')

            # 4. 解析 Spine
            spine_node = root.find(f'.//{ns_prefix}spine')
            if spine_node is not None:
                # toc 属性指代 ncx 的 id
                self.toc_id = spine_node.attrib.get('toc', '')
                
                # 预先获取所有的物理目录 ID 列表，并在解析 Spine 时将其剔除
                toc_item_ids = self.get_toc_item_ids()
                
                for itemref in spine_node.findall(f'.//{ns_prefix}itemref'):
                    idref = itemref.attrib.get('idref', '')
                    linear = itemref.attrib.get('linear', 'yes')
                    if idref:
                        manifest_item = self.manifest.get(idref)
                        if manifest_item:
                            self.original_spine_paths.append(self._resolve_path(manifest_item['href']))
                        
                        # 过滤掉物理目录，使其不出现在正文排版和前端预览章节中
                        if idref in toc_item_ids:
                            continue
                        self.spine.append(idref)
                        if manifest_item:
                            full_path = self._resolve_path(manifest_item['href'])
                            self.spine_paths.append(full_path)
                            
        except Exception as e:
            raise ValueError(f"解析 OPF 文件失败: {str(e)}")

    def get_toc_item_ids(self):
        """
        获取所有可能是物理目录 (TOC) 的 manifest item ID 列表。
        结合 properties="nav"、guide_toc_href、文件名启发式、NCX/NAV 系统目录反向文本映射以及链接密度结构化分析。
        """
        toc_ids = []
        import zhconv
        
        # 1. 寻找带有 properties="nav" 的 item (EPUB 3 规范)
        for item_id, item_info in self.manifest.items():
            properties = item_info.get('properties', '') or ''
            if properties and 'nav' in properties.split():
                toc_ids.append(item_id)
                
        # 2. 寻找 guide 中定义为 toc 的 href (EPUB 2 规范)
        if hasattr(self, 'guide_toc_href') and self.guide_toc_href:
            # guide_toc_href 可能是 "text/toc.xhtml#toc" 这种带锚点的格式，需要剥离锚点
            clean_href = self.guide_toc_href.split('#')[0]
            for item_id, item_info in self.manifest.items():
                if item_info.get('href') == clean_href:
                    if item_id not in toc_ids:
                        toc_ids.append(item_id)
 
        # 3. 解析系统的 NCX 目录文件并反向文本匹配 (针对多分册合并本及物理目录的终极检测)
        if hasattr(self, 'ncx_path') and self.ncx_path:
            try:
                ncx_content = self.read_text_file(self.ncx_path)
                root = ET.fromstring(ncx_content)
                ns_prefix = root.tag.split('}')[0] + '}' if root.tag.startswith('{') else ''
                ns = {'ncx': ns_prefix.strip('{}') if ns_prefix else ''}
                
                navpoints = root.findall('.//ncx:navPoint', ns)
                for np in navpoints:
                    label = np.find('./ncx:navLabel/ncx:text', ns)
                    content_tag = np.find('./ncx:content', ns)
                    
                    label_text = label.text if label is not None else ""
                    src = content_tag.attrib.get('src', '') if content_tag is not None else ""
                    
                    if not label_text or not src:
                        continue
                        
                    # 简繁转换并转为小写
                    clean_label = zhconv.convert(label_text, 'zh-cn').lower()
                    
                    # 匹配目录特征关键词
                    keywords = ['目录', '目次', 'contents', 'toc', 'mulu']
                    if any(kw in clean_label for kw in keywords):
                        # 剥离锚点
                        clean_href = src.split('#')[0]
                        
                        # 计算其在 zip 中的规范化相对路径
                        ncx_dir = os.path.dirname(self.ncx_path)
                        full_zip_path = os.path.normpath(os.path.join(ncx_dir, clean_href)).replace('\\', '/')
                        
                        # 在 manifest 中反向匹配对应的 ID
                        opf_dir = self.opf_dir
                        for item_id, item_info in self.manifest.items():
                            item_href = item_info.get('href', '')
                            item_full_path = os.path.normpath(os.path.join(opf_dir, item_href)).replace('\\', '/')
                            if item_full_path == full_zip_path:
                                if item_id not in toc_ids:
                                    toc_ids.append(item_id)
            except Exception:
                pass
 
        # 4. 解析 EPUB 3 的 NAV 导航文档反向文本匹配
        if hasattr(self, 'nav_path') and self.nav_path:
            try:
                nav_content = self.read_text_file(self.nav_path)
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(nav_content, 'html.parser')
                
                for a in soup.find_all('a'):
                    href = a.get('href', '')
                    text = a.get_text()
                    
                    if not href or not text:
                        continue
                        
                    clean_label = zhconv.convert(text, 'zh-cn').lower()
                    keywords = ['目录', '目次', 'contents', 'toc', 'mulu']
                    if any(kw in clean_label for kw in keywords):
                        clean_href = href.split('#')[0]
                        
                        nav_dir = os.path.dirname(self.nav_path)
                        full_zip_path = os.path.normpath(os.path.join(nav_dir, clean_href)).replace('\\', '/')
                        
                        opf_dir = self.opf_dir
                        for item_id, item_info in self.manifest.items():
                            item_href = item_info.get('href', '')
                            item_full_path = os.path.normpath(os.path.join(opf_dir, item_href)).replace('\\', '/')
                            if item_full_path == full_zip_path:
                                if item_id not in toc_ids:
                                    toc_ids.append(item_id)
            except Exception:
                pass
                         
        # 5. 寻找常见文件名的 item (作为备用的文件名启发式判断)
        for item_id, item_info in self.manifest.items():
            href = item_info.get('href', '').lower()
            filename = os.path.basename(href)
            name_without_ext, _ = os.path.splitext(filename)
            
            # 精确匹配常见目录文件名
            exact_match_names = {
                'toc', 'nav', 'catalog', 'mulu', 'contents', 'content', 
                'directory', 'index', 'tableofcontents', 'table_of_contents'
            }
            # 模糊匹配包含以下关键词 of 目录文件名
            fuzzy_keywords = {'toc', 'mulu', 'contents', 'navigation', 'catalog'}
            
            is_toc = False
            if name_without_ext in exact_match_names:
                is_toc = True
            elif any(kw in name_without_ext for kw in fuzzy_keywords):
                is_toc = True
                 
            if is_toc:
                if item_id not in toc_ids:
                    toc_ids.append(item_id)

        # 6. 发烧友级优化：基于页面超链接密度 (Link Density Heuristic) 的物理目录内容智能识别
        for item_id, item_info in self.manifest.items():
            if item_id in toc_ids:
                continue
                
            href = item_info.get('href', '')
            media_type = item_info.get('media-type', '') or ''
            if not ('html' in media_type.lower() or href.lower().endswith(('.html', '.xhtml', '.htm'))):
                continue
                
            try:
                full_path = self._resolve_path(href)
                html_content = self.read_text_file(full_path)
                if not html_content:
                    continue
                    
                from bs4 import BeautifulSoup
                # 采用极速的 xml 解析器提取核心结构
                soup = BeautifulSoup(html_content, "xml")
                body = soup.find("body")
                if not body:
                    continue
                    
                links = body.find_all("a")
                link_count = len(links)
                if link_count < 5:  # 链接数太少通常不是目录
                    continue
                    
                # 计算纯文本长度与超链接内文本长度
                total_text_clean = "".join(body.get_text().split())
                total_text_len = len(total_text_clean)
                if total_text_len == 0:
                    continue
                    
                link_text_clean = "".join("".join(a.get_text().split()) for a in links)
                link_text_len = len(link_text_clean)
                
                # 链接字数比率 (超链接文本字数占页面总字数的比例)
                link_density = link_text_len / total_text_len
                
                # 如果超链接文本占比超高（超过 75%）或者超链接比重占了段落/列表项的 80% 以上，即为物理目录
                p_count = len(body.find_all("p"))
                li_count = len(body.find_all("li"))
                block_count = p_count + li_count
                
                is_dense_toc = False
                if link_density >= 0.75:
                    is_dense_toc = True
                elif link_count >= 10 and block_count > 0 and (link_count / block_count) >= 0.8:
                    # 必须保证链接文本的字数占有一定的比例，防止被充满数字角标链接的段落正文误判
                    if link_density >= 0.15:
                        is_dense_toc = True
                    
                if is_dense_toc:
                    toc_ids.append(item_id)
            except Exception:
                pass
                    
        return toc_ids

    def _resolve_path(self, href):
        """将相对于 OPF 文件的路径解析为相对于 zip 根目录的路径"""
        # 兼容 URL 编码，如 %20 等
        from urllib.parse import unquote
        href_unquoted = unquote(href)
        
        if not self.opf_dir:
            return href_unquoted
        
        # 拼接并规范化路径，统一为 '/' 分隔符
        path = os.path.normpath(os.path.join(self.opf_dir, href_unquoted))
        return path.replace('\\', '/')

    def get_preview_chapters(self, count=2):
        """
        获取前 N 个章节的原文，用于实时预览。
        返回格式: [{"path": rel_path, "content": html_str}]
        """
        chapters = []
        # 筛选出主要的正文 xhtml/html 文件路径
        text_paths = []
        for path in self.spine_paths:
            # 根据后缀或 media-type 筛选
            # 查找 manifest 中对应的 media-type 是否为 html/xml
            text_paths.append(path)
            
        for path in text_paths[:count]:
            try:
                html_str = self.read_text_file(path)
                chapters.append({
                    "path": path,
                    "content": html_str
                })
            except Exception as e:
                # 容错：如果读取失败，继续尝试后续
                continue
        return chapters
