"""通用 EPUB 深度提取与排版重构工具 (extract_to_work.py)

特性与设计原则（基于第一性原理，完全消除书籍硬编码）：
1. 底层通用超链接与交互引擎（适用于任何单本或合集）：
   - 跨图表/正文/注释双向交叉引用拓扑图，自动归一化全局锚点，并在插图图注后统一生成紧凑规范的 [返回正文]；
   - 多体系注脚自适应配对提取（标准 noteref、类命名 footnote、成对数字互跳），完整继承注内子跳转；
   - 原生 HTML 复杂表格自适应转换为标准 Markdown 表格。
2. 自适应书籍结构识别引擎（单本 vs 合集通用）：
   - 自动基于 NCX / Nav 层级判定单本模式还是多卷合集模式；
   - 自动基于阅读序与图像特征配对单卷全屏彩封与白底扉页；
   - 启发式检测并过滤静态纯文本死目录页，由多看原生目录统一接管；
   - 启发式识别出版说明、版权与编委会，独立排版。
"""

import sys
from pathlib import Path

# 将项目 venv 的 site-packages 加入 sys.path，保证依赖正常导入
_venv_site = Path(__file__).resolve().parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists():
    sys.path.insert(0, str(_venv_site))

import os
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup


def is_html_file(name: str) -> bool:
    """判断文件是否为 HTML/XHTML 文档。"""
    return name.lower().endswith(('.html', '.xhtml', '.htm', '.xml'))


def strip_html_ext(name: str) -> str:
    """去除文件名末尾的 HTML/XHTML/XML 扩展名。"""
    return re.sub(r'\.(x?html?|xml)$', '', os.path.basename(name), flags=re.I)


def is_code_alt(alt):
    """判断图片 alt 是否为无意义的占位字符。"""
    if not alt:
        return True
    a = alt.strip().lower()
    if a in {'feiye', 'fy', 'cover', 'none', '0', '1', '2'}:
        return True
    if re.fullmatch(r'\d+[-_]\d+', a) or re.fullmatch(r'\d+', a):
        return True
    return False


def is_static_toc_page(soup):
    """启发式检测一个页面是否为静态纯文本目录页（死目录）。"""
    links = soup.find_all('a', href=True)
    if len(links) < 2:
        return False
    text = soup.get_text(strip=True)
    if not text:
        return False
    link_text_len = sum(len(a.get_text(strip=True)) for a in links)
    ratio = link_text_len / len(text)
    # 当超链接文本占比超 70% 且链接数不少于 2，或标题明确含“目录”且占比超 50% 时判定为静态目录
    is_toc_title = any(k in text[:30] for k in ('目录', '总目录', 'Contents', 'CONTENTS'))
    return (ratio > 0.7 and len(links) >= 2) or (is_toc_title and ratio > 0.5)


def extract_single_image(soup):
    """检查页面是否仅为单张全屏大图（如封面、白底扉页、彩插），返回图片文件名。"""
    img = soup.find('img') or soup.find('image')
    if not img:
        return None
    # 检查纯文本字数
    txt = soup.get_text(strip=True)
    if len(txt) > 30:  # 若有较多正文，不是纯图片页
        return None
    src = img.get('src') or img.get('xlink:href') or ''
    return os.path.basename(src) if src else None



def extract_feiye_info(soup):
    """检查并提取分卷文字扉页（书名、副标题、著者、译者、出版社）。"""
    raw = soup.get_text()
    if 'CIP' in raw or '图书在版编目' in raw or 'ISBN' in raw:
        return None
    has_shuming = bool(soup.find(class_=lambda c: c and any(k in str(c).lower() for k in ('shuming', 'feiye'))))
    has_title_tag = any('扉页' in (elem.get('title', '') or '') for elem in soup.find_all(attrs={'title': True}))
    if not (has_shuming or has_title_tag):
        return None

    title = ""
    sub = ""
    author = ""
    trans = ""
    pub = ""
    c1 = soup.find(class_=lambda c: c and any(k in str(c).lower() for k in ('calibre1', 'title', 'bookname')))
    if c1:
        title = c1.get_text(strip=True)
    for k in soup.find_all(class_=lambda c: c and any(x in str(c).lower() for x in ('kaiti', 'sub', 'author', 'trans'))):
        txt = k.get_text(strip=True)
        if not txt:
            continue
        if txt.startswith('——') or '—' in txt or txt.startswith('（'):
            sub = txt
        elif '著' in txt or '编' in txt:
            author = txt
        elif '译' in txt:
            trans = txt
    pub_el = soup.find(class_=lambda c: c and any(p in str(c).lower() for p in ('chubanshe', 'publisher', 'press')))
    if pub_el:
        pub = pub_el.get_text(strip=True)
    else:
        for d in soup.find_all(['div', 'p']):
            if '出版' in d.get_text():
                pub = d.get_text(strip=True)
                break
    if title:
        return {"title": title, "sub": sub, "author": author, "trans": trans, "pub": pub}
    return None

def clean_html_whitespace(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    cjk_re = r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\u3040-\u309f\u30a0-\u30ff]'
    text = re.sub(rf'({cjk_re})\s*\n\s*', r'\1', text)
    text = re.sub(rf'\s*\n\s*({cjk_re})', r'\1', text)
    text = re.sub(r'(\[\^[a-zA-Z0-9_\-]+\])\s*\n\s*', r'\1', text)
    text = re.sub(r'\s*\n\s*(\[\^[a-zA-Z0-9_\-]+\])', r'\1', text)
    text = re.sub(r'([）\)\],，。！？!?;；：:”’])\s*\n\s*', r'\1', text)
    text = re.sub(r'\s*\n\s*([（\(\[,，。！？!?;；：:“‘])', r'\1', text)
    text = re.sub(r'\s*\n\s*', ' ', text)
    return text.strip()

import argparse

def main():
    parser = argparse.ArgumentParser(description="通用 EPUB 深度提取与排版重构工具")
    parser.add_argument("epub", help="输入的原始 EPUB 文件路径")
    parser.add_argument("--cover", help="可选：指定自定义封面图片路径", default=None)
    args = parser.parse_args()

    src_epub = Path(args.epub).resolve()
    if not src_epub.exists():
        print(f"Error: {src_epub} does not exist")
        sys.exit(1)

    work_dir = Path("work").resolve()
    if work_dir.exists():
        print(f"[*] 清理历史工作目录: {work_dir.name}")
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    images_path = work_dir / "images"
    images_path.mkdir(parents=True)

    print(f"[*] 正在读取并解压 EPUB: {src_epub.name} ({src_epub.stat().st_size / (1024*1024):.2f} MB)")

    with zipfile.ZipFile(src_epub, 'r') as z:
        # =========================================================================
        # 1. 提取全书所有插图
        # =========================================================================
        image_files = [f for f in z.namelist() if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))]
        for im in image_files:
            im_data = z.read(im)
            out_name = os.path.basename(im)
            (images_path / out_name).write_bytes(im_data)

        print(f"[+] 已提取全部插图 {len(image_files)} 张至 {images_path}")

        # =========================================================================
        # 2. 封面图片检测与确定（完全消除硬编码）
        # =========================================================================
        cover_ref = ""
        user_specified_cover = None
        if args.cover and Path(args.cover).exists():
            user_specified_cover = Path(args.cover).resolve()
        else:
            # 自动探测与当前 EPUB 同名的封面文件
            for ext in ('.jpg', '.jpeg', '.png', '.webp'):
                cand1 = src_epub.with_name(f"{src_epub.stem}_cover{ext}")
                cand2 = src_epub.with_name(f"{src_epub.stem}{ext}")
                if cand1.exists():
                    user_specified_cover = cand1
                    break
                elif cand2.exists() and cand2 != src_epub:
                    user_specified_cover = cand2
                    break

        if user_specified_cover:
            shutil.copy(user_specified_cover, images_path / "cover.jpg")
            cover_ref = "images/cover.jpg"
            print(f"[+] 采用指定的专属封面: {user_specified_cover.name}")

        # =========================================================================
        # 3. 解析 OPF 与元数据
        # =========================================================================
        opf_path = next((n for n in z.namelist() if n.endswith('.opf')), None)
        if not opf_path:
            print("[-] 未在 EPUB 中找到 OPF 文件")
            sys.exit(1)

        opf_xml = z.read(opf_path).decode('utf-8', errors='ignore')
        opf_root = ET.fromstring(opf_xml)
        opf_dir = os.path.dirname(opf_path)

        title_el = opf_root.find('.//{http://purl.org/dc/elements/1.1/}title')
        title = title_el.text.strip() if title_el is not None and title_el.text else src_epub.stem
        author_el = opf_root.find('.//{http://purl.org/dc/elements/1.1/}creator')
        author = author_el.text.strip() if author_el is not None and author_el.text else "佚名"
        desc_el = opf_root.find('.//{http://purl.org/dc/elements/1.1/}description')
        desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

        # 构建 spine 线性阅读序列
        manifest = {item.attrib['id']: item.attrib['href'] for item in opf_root.findall('.//{http://www.idpf.org/2007/opf}item')}
        spine_files = []
        for itemref in opf_root.findall('.//{http://www.idpf.org/2007/opf}itemref'):
            idref = itemref.attrib.get('idref')
            if idref in manifest:
                rel = manifest[idref]
                full_rel = os.path.normpath(os.path.join(opf_dir, rel)).replace('\\', '/')
                spine_files.append((rel, full_rel))

        # 若未指定专属封面，优先尝试从 OPF manifest 提取 cover-image，再回退到首个全屏页面
        if not cover_ref:
            cover_item = opf_root.find(".//{http://www.idpf.org/2007/opf}item[@properties='cover-image']")
            if cover_item is None:
                for item in opf_root.findall(".//{http://www.idpf.org/2007/opf}item"):
                    m_type = item.attrib.get('media-type', '')
                    iid = item.attrib.get('id', '').lower()
                    ihref = item.attrib.get('href', '').lower()
                    if m_type.startswith('image/') and ('cover' in iid or 'cover' in ihref):
                        cover_item = item
                        break
            if cover_item is not None:
                c_href = os.path.basename(cover_item.attrib.get('href', ''))
                if (images_path / c_href).exists():
                    if c_href.lower() != "cover.jpg":
                        shutil.copy(images_path / c_href, images_path / "cover.jpg")
                    cover_ref = "images/cover.jpg"
                    print(f"[+] 自动从 OPF manifest 识别封面: {c_href}")

        if not cover_ref and spine_files:
            first_rel, first_full = spine_files[0]
            first_soup = BeautifulSoup(z.read(first_full), 'html.parser')
            first_img = extract_single_image(first_soup)
            if first_img and (images_path / first_img).exists():
                if first_img.lower() != "cover.jpg":
                    shutil.copy(images_path / first_img, images_path / "cover.jpg")
                cover_ref = "images/cover.jpg"
                print(f"[+] 自动采用首个全屏页面图像作为封面: {first_img}")

        # =========================================================================
        # 4. 自适应书籍结构识别（单本 vs 多卷合集）
        # =========================================================================
        ncx_path = next((n for n in z.namelist() if n.endswith('.ncx')), None)
        is_multi_volume = False
        volume_map = {}   # start_file -> (vol_title, cover_img, feiye_img)
        chap_files = {}   # file_base -> chapter_title
        spine_file_bases = [os.path.basename(rel) for rel, _ in spine_files]

        if ncx_path:
            ncx_xml = z.read(ncx_path).decode('utf-8', errors='ignore')
            n_root = ET.fromstring(ncx_xml)
            nav_map = n_root.find('.//{http://www.daisy.org/z3986/2005/ncx/}navMap')
            if nav_map is not None:
                top_navpoints = nav_map.findall('{http://www.daisy.org/z3986/2005/ncx/}navPoint')
                has_subs = any(bool(np.findall('{http://www.daisy.org/z3986/2005/ncx/}navPoint')) for np in top_navpoints)
                if has_subs:
                    is_multi_volume = True

                for np in top_navpoints:
                    lbl_el = np.find('{http://www.daisy.org/z3986/2005/ncx/}navLabel/{http://www.daisy.org/z3986/2005/ncx/}text')
                    src_el = np.find('{http://www.daisy.org/z3986/2005/ncx/}content')
                    if lbl_el is None or src_el is None:
                        continue
                    v_title = lbl_el.text.strip()
                    v_src = os.path.basename(src_el.attrib.get('src', '').split('#')[0])
                    subs = np.findall('{http://www.daisy.org/z3986/2005/ncx/}navPoint')

                    if is_multi_volume and subs:
                        # 查找该卷的前置彩封与扉页大图
                        cov_img = None
                        feiye_img = None
                        if v_src in spine_file_bases:
                            idx = spine_file_bases.index(v_src)
                            # 卷首文件本身如果是单图，作为扉页
                            v_soup = BeautifulSoup(z.read(spine_files[idx][1]), 'html.parser')
                            feiye_img = extract_single_image(v_soup)
                            # 前一个文件如果是单图，作为该卷彩封
                            if idx > 0:
                                prev_rel, prev_full = spine_files[idx - 1]
                                prev_soup = BeautifulSoup(z.read(prev_full), 'html.parser')
                                cov_img = extract_single_image(prev_soup)
                        volume_map[v_src] = (v_title, cov_img, feiye_img)

                        for snp in subs:
                            slbl_el = snp.find('{http://www.daisy.org/z3986/2005/ncx/}navLabel/{http://www.daisy.org/z3986/2005/ncx/}text')
                            ssrc_el = snp.find('{http://www.daisy.org/z3986/2005/ncx/}content')
                            if slbl_el is not None and ssrc_el is not None:
                                s_title = slbl_el.text.strip()
                                s_src = os.path.basename(ssrc_el.attrib.get('src', '').split('#')[0])
                                if s_title not in ('目录', '总目录', 'Contents') and s_src not in chap_files:
                                    chap_files[s_src] = s_title
                    else:
                        if v_title not in ('目录', '总目录', 'Contents') and v_src not in chap_files:
                            chap_files[v_src] = v_title

        print(f"[+] 自适应识别书籍结构: {'多卷合集 (' + str(len(volume_map)) + ' 卷)' if is_multi_volume else '单本标准书籍'}")

        # =========================================================================
        # 5. 启发式检测静态纯目录页与全屏前置图片页
        # =========================================================================
        toc_files_to_skip = set()
        fullscreen_map = {}  # file_base -> (title, img_src)

        for rel, full_rel in spine_files:
            fb = os.path.basename(rel)
            if not is_html_file(fb):
                continue
            soup = BeautifulSoup(z.read(full_rel), 'html.parser')
            if is_static_toc_page(soup):
                toc_files_to_skip.add(fb)

            # 检查是否为单卷彩封或扉页（已在 volume_map 中记录的）
            for vs, (vt, c_img, f_img) in volume_map.items():
                if fb == vs and f_img:
                    fullscreen_map[fb] = (f"{vt} 扉页", f_img)
                elif vs in spine_file_bases and spine_file_bases.index(vs) > 0 and fb == spine_file_bases[spine_file_bases.index(vs) - 1] and c_img:
                    fullscreen_map[fb] = (f"{vt} 封面", c_img)

        print(f"[+] 自动检测并跳过静态目录页 {len(toc_files_to_skip)} 个")

        # =========================================================================
        # 6. 底层通用超链接与全书交互预检 (Link Auditor)
        # =========================================================================
        audit_footnotes = 0
        audit_xrefs = 0
        audit_tables = 0

        for rel, full_rel in spine_files:
            fb = os.path.basename(rel)
            if fb in toc_files_to_skip or not is_html_file(fb):
                continue
            s_audit = BeautifulSoup(z.read(full_rel), 'html.parser')
            for a in s_audit.find_all('a'):
                href = a.get('href', '')
                aid = a.get('id', '')
                cls_str = " ".join(a.get('class', [])) if isinstance(a.get('class'), list) else str(a.get('class', ''))
                if any(k in href.lower() or k in aid.lower() or k in cls_str.lower() for k in ('note', 'foot', 'fo', 'fn', 'annot')):
                    audit_footnotes += 1
                elif href and not href.startswith('http') and not href.startswith('#sigil_toc'):
                    audit_xrefs += 1
            audit_tables += len(s_audit.find_all('table'))

        print(f"[+] 全书超链接预检完成：")
        print(f"    - 注释互跳标记: 约 {audit_footnotes} 处")
        print(f"    - 图表/正文/章节交叉跳转: 约 {audit_xrefs} 处")
        print(f"    - 原生表格 (table): {audit_tables} 个")

        # =========================================================================
        # 7. 逐章抽取与 Markdown 结构化转换
        # =========================================================================
        md_lines = []
        md_lines.append("---")
        md_lines.append(f"title: {title}")
        md_lines.append(f"author: {author}")
        if desc:
            clean_desc = "\n  ".join(desc.strip().splitlines())
            md_lines.append(f"description: |\n  {clean_desc}")
        if cover_ref:
            md_lines.append(f"cover: {cover_ref}")
        md_lines.append("title_page: false")
        md_lines.append("---")
        md_lines.append("")

        total_footnotes_count = 0
        current_volume_title = title

        for rel_name, full_zip_path in spine_files:
            file_base = os.path.basename(rel_name)
            if file_base in toc_files_to_skip or not is_html_file(file_base):
                continue

            # 处理合集分卷首节点
            if is_multi_volume and file_base in volume_map:
                v_title, c_img, f_img = volume_map[file_base]
                current_volume_title = v_title
                md_lines.append(f"# {v_title}")
                md_lines.append("")
                # 卷首节点生成卷封面与卷扉页全屏图
                if c_img:
                    md_lines.append(f"![{v_title} 封面](images/{c_img})")
                    md_lines.append("")
                if f_img:
                    md_lines.append("## 扉页 [fullscreen]")
                    md_lines.append("")
                    md_lines.append(f"![扉页](images/{f_img})")
                    md_lines.append("")
                continue

            # 处理全屏单图（如单本白底扉页）
            if file_base in fullscreen_map:
                fs_title, fs_img = fullscreen_map[file_base]
                # 多卷合集下，分卷封面与扉页已由 volume_map 统一规范承载为纯净全屏封面，跳过外部重复节点
                if is_multi_volume and any(fs_img in (v[1], v[2]) for v in volume_map.values()):
                    continue
                md_lines.append(f"## {fs_title} [fullscreen]")
                md_lines.append("")
                md_lines.append(f"![{fs_title}](images/{fs_img})")
                md_lines.append("")
                continue

            html_data = z.read(full_zip_path).decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html_data, 'html.parser')

            # 通用检测：正文前的前置纯彩插/图版页面（如每卷卷首的高清文物彩页群）
            raw_txt = soup.get_text(strip=True)
            all_imgs = [os.path.basename(im.get('src', '')) for im in soup.find_all('img') if im.get('src')]
            if all_imgs and len(raw_txt) < 30 and not is_static_toc_page(soup) and '附录' not in raw_txt and '年表' not in raw_txt:
                if file_base not in chap_files or any(k in chap_files.get(file_base, '') for k in ('彩', '插图', '图版')):
                    chap_md = []
                    for idx, img_fn in enumerate(all_imgs):
                        if (images_path / img_fn).exists():
                            chap_md.append("## 彩插 [fullscreen]")
                            chap_md.append("")
                            chap_md.append(f"![彩插](images/{img_fn})")
                            chap_md.append("")
                    if chap_md:
                        md_lines.extend(chap_md)
                        continue

            # 优先检查并提取原书扉页（含总扉页 part0000 及各卷文字扉页）
            feiye_info = extract_feiye_info(soup)
            if feiye_info:
                md_lines.append("## 扉页 [feiye]")
                md_lines.append("")
                md_lines.append('<div class="feiye-wrap">')
                if feiye_info["title"]:
                    md_lines.append(f'<p class="feiye-title">{feiye_info["title"]}</p>')
                if feiye_info["sub"]:
                    md_lines.append(f'<p class="feiye-sub">{feiye_info["sub"]}</p>')
                if feiye_info["author"]:
                    md_lines.append(f'<p class="feiye-author">{feiye_info["author"]}</p>')
                if feiye_info["trans"]:
                    md_lines.append(f'<p class="feiye-trans">{feiye_info["trans"]}</p>')
                if feiye_info["pub"]:
                    md_lines.append(f'<p class="feiye-pub">{feiye_info["pub"]}</p>')
                md_lines.append('</div>')
                md_lines.append("")
                continue

            # 辅助函数：判断是否为各类注脚/弹注相关链接（严格排除图表与插图 b-01, fig-1 等）
            def is_footnote_link(a_tag):
                h = a_tag.get('href', '')
                i = a_tag.get('id', '')
                c = " ".join(a_tag.get('class', [])) if isinstance(a_tag.get('class'), list) else str(a_tag.get('class', ''))
                ep = str(a_tag.get('epub:type', '')).lower()
                if any(k in c.lower() for k in ('footnote', 'duokan-footnote', 'noteref')):
                    return True
                if 'noteref' in ep:
                    return True
                # 显式排除图表、照片与段落引用 ID
                if re.search(r'#(b-|fig|img|table|tab|p-)', h, re.I) or re.search(r'^(b-|fig|img|table|tab|p-)', i, re.I):
                    return False
                if re.search(r'#(fo|fn|note|footnote|annot|comment|foref|noteref|ref|fnref|back|noteback)[_\-]?\d+', h, flags=re.I):
                    return True
                if re.search(r'#[ab]0\d+$', h, flags=re.I):
                    return True
                if re.search(r'^(foref|noteref|ref|fnref|note|noteback)[_\-]?\d+', i, flags=re.I):
                    return True
                if re.search(r'^[ab]0\d+$', i, flags=re.I):
                    return True
                return False

            # -----------------------------------------------------------------
            # A. 全文图表/地图/正文跨章交叉引用转换为标准 Markdown 链接（优先执行）
            # -----------------------------------------------------------------
            for a in soup.find_all('a'):
                href = a.get('href', '')
                if not href or href.startswith('http') or '#sigil_toc' in href:
                    continue
                if is_footnote_link(a):
                    continue

                txt = a.get_text(strip=True)
                if not txt:
                    continue

                if '#' in href:
                    t_f, t_id = href.split('#', 1)
                    t_f = t_f if t_f else file_base
                else:
                    t_f, t_id = href, ""

                t_base = strip_html_ext(t_f)
                xref_key = f"xref_{t_base}_{t_id}" if t_id else f"xref_{t_base}"
                a.replace_with(f"[{txt}](#{xref_key})")

            # -----------------------------------------------------------------
            # B. 双向多体系注释深度提取（Universal Footnote Extractor）
            # -----------------------------------------------------------------
            footnotes = {}

            # 1. 结构化容器定义（如多看 <ol class="duokan-footnote-content">、<section class="footnotes">）
            note_containers = soup.find_all(['ol', 'ul', 'div', 'section'], class_=lambda c: c and any(k in str(c).lower() for k in ('footnote', 'duokan-footnote', 'notes', 'annot')))
            for container in note_containers:
                for item in container.find_all(['li', 'p', 'div']):
                    item_id = item.get('id', '')
                    num_match = re.search(r'\d+', item_id) if item_id else None
                    if not num_match:
                        txt_head = item.get_text(strip=True)[:15]
                        num_match = re.search(r'\[?(\d+)\]?', txt_head)
                    if num_match:
                        num = num_match.group(1) if num_match.lastindex else num_match.group(0)
                        num = num.lstrip('0') or '1'
                        # 清理内部反跳链接与序号标签
                        for back_a in item.find_all('a'):
                            back_href = back_a.get('href', '')
                            back_txt = back_a.get_text(strip=True)
                            if any(k in back_href.lower() for k in ('ref', 'note', 'back', 'top', '#foref')) or re.fullmatch(r'\[?\d+\]?', back_txt):
                                back_a.decompose()
                        raw_txt = item.get_text(strip=True)
                        raw_txt = re.sub(r'^\s*\[?\d+\]?[\.、\s]*', '', raw_txt)
                        if raw_txt:
                            footnotes[num] = raw_txt
                container.decompose()

            def is_note_def_id(val):
                if not val:
                    return False
                s = str(val)
                if s.startswith(('b-', 'fig', 'img', 'table', 'tab', 'p-')):
                    return False
                return bool(re.match(r'^(note|fo|fn|footnote|annot|comment)[_\-]?\d+[a-z]?$', s, flags=re.I) or re.match(r'^[ab]0\d+$', s, flags=re.I))

            def is_real_note_def_a(a_tag):
                if not getattr(a_tag, 'attrs', None) or getattr(a_tag, 'decomposed', False):
                    return False
                aid = a_tag.get('id', '')
                href = a_tag.get('href', '')
                if not (is_footnote_link(a_tag) or any(k in aid.lower() for k in ('note', 'fn', 'fo'))):
                    return False
                # 特征 1: href 包含返回正文的标记 (back, ref, foref) 或自身包含 def, n
                if any(k in href.lower() for k in ('back', 'ref', 'foref', 'noteback')):
                    return True
                if re.search(r'note\d+n$', aid, re.I) or re.search(r'def', aid, re.I):
                    return True
                # 特征 2: 父段落属于明确的注释类
                parent = a_tag.find_parent(['p', 'li', 'div'])
                if parent:
                    p_cls = " ".join(parent.get('class', [])) if isinstance(parent.get('class'), list) else str(parent.get('class', ''))
                    if any(k in p_cls.lower() for k in ('calibre18', 'footnote', 'notes', 'annot')):
                        return True
                    # 特征 3: a_tag 位于段落最开头且段落以数字或序号开头
                    txt = parent.get_text(strip=True)
                    if re.match(r'^\[?\d+\]?', txt) and (not a_tag.previous_sibling or not str(a_tag.previous_sibling).strip()):
                        if a_tag.parent and a_tag.parent.name not in ('sup', 'span'):
                            return True
                return False

            # 2. 独立段落/列表项带有注释 ID 定义
            for item in soup.find_all(['li', 'div', 'p'], id=is_note_def_id):
                if getattr(item, 'decomposed', False) or not getattr(item, 'attrs', None):
                    continue
                item_id = item.get('id', '')
                m = re.search(r'\d+', item_id)
                if m:
                    num = m.group(0).lstrip('0') or '1'
                    if num not in footnotes:
                        for back_a in item.find_all('a'):
                            back_href = back_a.get('href', '')
                            back_txt = back_a.get_text(strip=True)
                            if any(k in back_href.lower() for k in ('ref', 'note', 'back', 'top', '#a', '#foref')) or re.fullmatch(r'\[?\d+\]?', back_txt):
                                back_a.decompose()
                        raw_txt = item.get_text(strip=True)
                        raw_txt = re.sub(r'^\s*\[?\d+\]?[\.、\s]*', '', raw_txt)
                        if raw_txt:
                            footnotes[num] = raw_txt
                    item.decompose()

            # 3. 锚点 <a> 标签自身为定位点
            for a_note in soup.find_all('a'):
                if is_real_note_def_a(a_note):
                    if getattr(a_note, 'decomposed', False) or not getattr(a_note, 'attrs', None):
                        continue
                    aid = a_note.get('id', '')
                    m = re.search(r'\d+', aid)
                    if m:
                        num = m.group(0).lstrip('0') or '1'
                        if num not in footnotes:
                            parent_p = a_note.find_parent(['p', 'div', 'li'])
                            if parent_p and not getattr(parent_p, 'decomposed', False) and getattr(parent_p, 'attrs', None) is not None:
                                for back_a in parent_p.find_all('a'):
                                    back_href = back_a.get('href', '')
                                    back_txt = back_a.get_text(strip=True)
                                    if any(k in back_href.lower() for k in ('ref', 'note', 'back', 'top', '#a', '#foref')) or re.fullmatch(r'\[?\d+\]?', back_txt):
                                        back_a.decompose()
                                raw_txt = parent_p.get_text(strip=True)
                                raw_txt = re.sub(r'^\s*\[?\d+\]?[\.、\s]*', '', raw_txt)
                                if raw_txt:
                                    footnotes[num] = raw_txt
                                parent_p.decompose()

            # 4. 正文中的注释引用转换为标准多看标记 [^key]
            for a_ref in soup.find_all('a'):
                if is_footnote_link(a_ref) and not is_real_note_def_a(a_ref):
                    href = a_ref.get('href', '')
                    aid = a_ref.get('id', '')
                    target_anchor = href.split('#')[1] if '#' in href else href
                    m = re.search(r'\d+', target_anchor) or re.search(r'\d+', aid)
                    if m:
                        num = m.group(0).lstrip('0') or '1'
                        unique_key = f"{strip_html_ext(file_base)}_{num}"
                        wrapper = a_ref
                        p_parent = a_ref.parent
                        if p_parent and p_parent.name in ('sup', 'span'):
                            if len(p_parent.get_text(strip=True)) <= len(a_ref.get_text(strip=True)) + 2:
                                wrapper = p_parent
                        wrapper.replace_with(f"[^{unique_key}]")
                    else:
                        a_ref.decompose()

            chap_md = []

            # 注入章节标题：版权信息 / 编委会 / NCX 章节标题
            raw_txt_full = soup.get_text(separator=' ', strip=True)
            is_cip = ('图书在版编目' in raw_txt_full or '（CIP）' in raw_txt_full) and ('ISBN' in raw_txt_full or '版权' in raw_txt_full)
            is_board = ('【编辑委员】' in raw_txt_full or '【编委会】' in raw_txt_full or '编辑委员' in raw_txt_full) and len(raw_txt_full) < 300
            
            raw_title = None
            if is_cip:
                raw_title = "版权信息"
            elif is_board:
                raw_title = "编委会"
            elif file_base in chap_files:
                raw_title = chap_files[file_base]

            if raw_title:
                is_kaiti_chap = False
                clean_t = raw_title.strip()
                if any(k in clean_t for k in ('代序', '代译序', '自序', '原序', '中文版序', '译者序')) and not any(k in clean_t for k in ('序章', '序幕', '第')):
                    is_kaiti_chap = True
                elif clean_t in ('代序', '代译序'):
                    is_kaiti_chap = True
                if not is_kaiti_chap and raw_title not in ('版权信息', '编委会'):
                    p_all = soup.find_all('p')
                    if p_all:
                        kaiti_count = sum(1 for p in p_all if any('kaiti' in str(c).lower() for c in p.get('class', [])))
                        if kaiti_count / len(p_all) > 0.6:
                            is_kaiti_chap = True
                kaiti_flag = " [kaiti]" if is_kaiti_chap else ""
                injected_title = f"## {raw_title}{kaiti_flag}"
                chap_md.append(injected_title)
                chap_md.append("")

            body = soup.find('body')
            if not body:
                continue

            # 编委会页面结构化输出：纯结构自适应居中版心排版（100% 通用，无任何特定书名硬编码）
            if is_board:
                chap_md.append('<div class="verse" style="text-align: center; margin: 2em auto;">')
                
                # 收集页面内所有有效文本行（按出现顺序保序去重）
                raw_board_lines = []
                seen_lines = set()
                for p_el in body.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'div']):
                    t_line = clean_html_whitespace(p_el.get_text(strip=True))
                    if t_line and t_line not in seen_lines and not any(k in t_line for k in ('<!DOCTYPE', 'html', 'head', 'body')):
                        seen_lines.add(t_line)
                        raw_board_lines.append(t_line)

                # 寻找【编委会】/【编辑委员】核心锚点行的索引
                tag_idx = -1
                for idx, line in enumerate(raw_board_lines):
                    if any(k in line for k in ('【编辑委员】', '【编委会】', '编辑委员', '编委会', '编辑委员会')):
                        tag_idx = idx
                        break

                for idx, line in enumerate(raw_board_lines):
                    if idx == tag_idx:
                        # 编委会板块标签：加粗 + 主题点缀色
                        chap_md.append(f'<p class="center" style="font-weight: bold; margin: 1.2em 0 0.6em; color: #a08a6a; text-indent: 0; text-align: center;">{line}</p>')
                    elif tag_idx != -1 and idx < tag_idx:
                        # 标签之前的行：自动判定为前置丛书名或分卷名，加粗居中
                        size_style = 'font-size: 1.25em; ' if (idx == tag_idx - 1 and len(line) <= 15) else ''
                        chap_md.append(f'<p class="center" style="font-weight: bold; {size_style}margin-bottom: 0.4em; text-indent: 0; text-align: center;">{line}</p>')
                    else:
                        # 标签之后的行：委员学者名单列表，规整居中排列
                        chap_md.append(f'<p class="center" style="margin: 0.4em 0; text-indent: 0; text-align: center;">{line}</p>')

                chap_md.append('</div>')
                chap_md.append("")
                md_lines.extend(chap_md)
                continue

            # -----------------------------------------------------------------
            # C. 处理图文包裹块：div.alone / div.chatu / figure
            # -----------------------------------------------------------------
            for div_alone in body.find_all(['div', 'figure'], class_=lambda c: c and any(k in str(c).lower() for k in ('alone', 'image', 'figure', 'illus', 'chatu'))):
                imgs = div_alone.find_all('img')
                caption_p = div_alone.find(['p', 'div'], class_=lambda c: c and any(k in str(c).lower() for k in ('picture', 'caption', 'title', 'tushuo')))
                caption_text = caption_p.get_text(strip=True) if caption_p else ""

                target_aid = None
                if not caption_text:
                    nxt = div_alone.find_next_sibling()
                    if nxt and nxt.name in ('p', 'figcaption') and nxt.get('class') and any(k in str(c).lower() for c in nxt.get('class') for k in ('picture', 'caption')):
                        caption_text = nxt.get_text(strip=True)
                        nxt_id = nxt.get('id') or (nxt.find(id=True)['id'] if nxt.find(id=True) else None)
                        if nxt_id:
                            target_aid = f"xref_{strip_html_ext(file_base)}_{nxt_id}"
                        nxt.decompose()

                # 检查是否存在目标锚点 ID
                if not target_aid:
                    if caption_p and caption_p.get('id'):
                        target_aid = f"xref_{strip_html_ext(file_base)}_{caption_p['id']}"
                    elif div_alone.get('id'):
                        target_aid = f"xref_{strip_html_ext(file_base)}_{div_alone['id']}"
                    else:
                        for child in div_alone.find_all(id=True):
                            target_aid = f"xref_{strip_html_ext(file_base)}_{child['id']}"
                            break

                anchor_prefix = f"{{#{target_aid}}} " if target_aid else ""

                replacement_tags = []
                for img_item in imgs:
                    src = os.path.basename(img_item.get('src', ''))
                    if src and (images_path / src).exists():
                        alt = img_item.get('alt', '').strip()
                        cap = caption_text if caption_text else (alt if not is_code_alt(alt) else "")
                        p_img = soup.new_tag('p')
                        p_img['class'] = 'md-image-container'
                        p_img.string = f"![{anchor_prefix}{cap}](images/{src})"
                        replacement_tags.append(p_img)
                        anchor_prefix = ""  # 仅第一张图附加锚点

                if replacement_tags:
                    first = replacement_tags[0]
                    div_alone.replace_with(first)
                    for extra in replacement_tags[1:]:
                        first.insert_after(extra)
                        first = extra
                else:
                    div_alone.decompose()

            # -----------------------------------------------------------------
            # D. 遍历正文、标题与表格
            # -----------------------------------------------------------------
            clean_injected_text = injected_title.lstrip('#').strip() if file_base in chap_files else ""

            for elem in body.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'blockquote', 'table', 'img']):
                if elem.name == 'img':
                    src = os.path.basename(elem.get('src', ''))
                    if src and (images_path / src).exists():
                        alt = elem.get('alt', '').strip()
                        cap = alt if not is_code_alt(alt) else ""
                        chap_md.append(f"![{cap}](images/{src})")
                        chap_md.append("")
                elif elem.name == 'table':
                    # 原生表格转换为 Markdown Table
                    rows = []
                    for tr in elem.find_all('tr'):
                        cells = [c.get_text(strip=True) for c in tr.find_all(['td', 'th'])]
                        if cells:
                            rows.append(cells)
                    if rows:
                        max_cols = max(len(r) for r in rows)
                        norm_rows = [r + [''] * (max_cols - len(r)) for r in rows]
                        chap_md.append("| " + " | ".join(norm_rows[0]) + " |")
                        chap_md.append("| " + " | ".join(["---"] * max_cols) + " |")
                        for r in norm_rows[1:]:
                            chap_md.append("| " + " | ".join(r) + " |")
                        chap_md.append("")
                elif elem.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                    cls = elem.get('class', [])
                    cls_str = " ".join(cls) if isinstance(cls, list) else str(cls)
                    t = elem.get_text(strip=True)
                    if not t:
                        continue

                    # 检查是否与本章注入的章标题重复
                    if clean_injected_text and (t == clean_injected_text or t in clean_injected_text or clean_injected_text in t):
                        continue

                    elem_id = elem.get('id') or (elem.find(id=True)['id'] if elem.find(id=True) else "")
                    if elem_id and 'sigil_toc' in elem_id.lower():
                        elem_id = ""
                    anchor_prefix = f"{{#xref_{strip_html_ext(file_base)}_{elem_id}}}" if elem_id else ""

                    if anchor_prefix:
                        chap_md.append(anchor_prefix)
                        chap_md.append("")

                    if t.strip() in ('【编辑委员】', '【编委会】', '编辑委员', '编委会'):
                        continue

                    # 彻底过滤正文中与已注入章节主标题重复的标题，消除双重重复大标题
                    def norm_t(s):
                        return re.sub(r'[\s\u3000\-_—：:]', '', s).strip()
                    if raw_title and norm_t(t) == norm_t(raw_title):
                        continue

                    # 语义层级自适应映射
                    if file_base in chap_files:
                        if elem.name in ('h1', 'h2') or 'heading2' in cls_str:
                            chap_md.append(f"### {t}")
                        elif elem.name == 'h3' or 'heading3' in cls_str or 'heading4' in cls_str:
                            chap_md.append(f"#### {t}")
                        else:
                            chap_md.append(f"##### {t}")
                    else:
                        if elem.name == 'h1' or 'heading-1' in cls_str:
                            chap_md.append(f"## {t}")
                        elif elem.name == 'h2' or 'heading2' in cls_str:
                            chap_md.append(f"### {t}")
                        elif elem.name == 'h3' or 'heading3' in cls_str:
                            chap_md.append(f"#### {t}")
                        else:
                            chap_md.append(f"##### {t}")
                    chap_md.append("")
                elif elem.name == 'p':
                    # 关键修复 1：引文内部的 p 不作为独立正文输出，避免重复
                    if elem.find_parent('blockquote'):
                        continue

                    cls = elem.get('class', [])
                    cls_str = " ".join(cls) if isinstance(cls, list) else str(cls)
                    # 严格判断右对齐与落款署名，排除包含 'copyright' 的版权段落误判
                    is_right = any(k in cls_str.lower() for k in ('right', 'signature', 'kaiti5', 'luokuan')) and 'copyright' not in cls_str.lower()

                    # 检查是否为带有锚点 ID 的目标段落（如制度名、表名、小节名）
                    elem_id = elem.get('id')
                    if not elem_id:
                        for child in elem.find_all(id=True):
                            elem_id = child['id']
                            break

                    anchor_prefix = f"{{#xref_{strip_html_ext(file_base)}_{elem_id}}} " if elem_id else ""

                    # 替换内部显式 <br> 为换行标记，普通 HTML 源码换行由 clean_html_whitespace 规范化，绝不断开注标段落
                    for br in elem.find_all('br'):
                        br.replace_with('__EXPLICIT_BR__')

                    raw_lines = elem.get_text().split('__EXPLICIT_BR__')
                    lines = [clean_html_whitespace(l) for l in raw_lines if clean_html_whitespace(l)]
                    if not lines:
                        continue

                    if is_right:
                        for l in lines:
                            chap_md.append(f'<p class="right">{anchor_prefix}{l}</p>')
                            anchor_prefix = ""
                        chap_md.append("")
                    else:
                        for l in lines:
                            if l.startswith('![') and l.endswith(')'):
                                chap_md.append(l)
                            else:
                                chap_md.append(f"{anchor_prefix}{l}")
                            anchor_prefix = ""
                        chap_md.append("")
                elif elem.name == 'blockquote':
                    # 关键修复 2：结构化提取 blockquote，保留诗歌换行与落款样式
                    p_list = elem.find_all('p')
                    if p_list:
                        for p_item in p_list:
                            p_cls = " ".join(p_item.get('class', [])) if isinstance(p_item.get('class'), list) else str(p_item.get('class', ''))
                            is_p_right = (any(k in p_cls.lower() for k in ('right', 'signature', 'kaiti5', 'luokuan')) and 'copyright' not in p_cls.lower()) or any(p_item.get_text(strip=True).startswith(k) for k in ('——', '--'))
                            for br in p_item.find_all('br'):
                                br.replace_with('__EXPLICIT_BR__')
                            raw_lines = p_item.get_text().split('__EXPLICIT_BR__')
                            lines = [clean_html_whitespace(l) for l in raw_lines if clean_html_whitespace(l)]
                            for l in lines:
                                if is_p_right:
                                    chap_md.append(f"> <p class=\"right\">{l}</p>")
                                else:
                                    chap_md.append(f"> {l}")
                    else:
                        for r_line in elem.get_text().splitlines():
                            cleaned = clean_html_whitespace(r_line)
                            if cleaned:
                                chap_md.append(f"> {cleaned}")
                            r_line = r_line.strip()
                            if r_line:
                                if r_line.startswith(('——', '--')):
                                    chap_md.append(f"> <p class=\"right\">{r_line}</p>")
                                else:
                                    chap_md.append(f"> {r_line}")
                    chap_md.append("")

            # E. 追加本章注释定义
            if footnotes:
                chap_md.append("")
                for f_num, f_text in footnotes.items():
                    unique_key = f"{strip_html_ext(file_base)}_{f_num}"
                    chap_md.append(f"[^{unique_key}]: {f_text}")
                    total_footnotes_count += 1
                chap_md.append("")

            md_lines.extend(chap_md)

        # 写入中间稿 book.md
        (work_dir / "book.md").write_text("\n".join(md_lines), encoding='utf-8')

        # 写入辅助样式（仅保留必要的楷体与落款类，保持多看原生典雅排版规范与花饰线不变）
        book_css = """/* 多看精排辅助样式 */
body.kaiti-body p, body.kaiti-body p.tx { font-family: "DK-KAITI", "Kaiti SC", "STKaiti", "KaiTi", serif; }
blockquote p.right, p.right { text-align: right; text-indent: 0; duokan-text-indent: 0; font-family: "DK-KAITI", "Kaiti SC", "STKaiti", "KaiTi", serif; margin: 0.6em 0 0.2em; color: #555; }
.feiye-wrap { text-align: center; padding-top: 25%; }
.feiye-title { font-family: "DK-HEITI", "PingFang SC", sans-serif; font-size: 1.8em; font-weight: bold; margin-bottom: 0.5em; text-indent: 0; duokan-text-indent: 0; }
.feiye-sub { font-family: "DK-KAITI", "Kaiti SC", serif; font-size: 1.1em; margin-bottom: 1.5em; color: #555; text-indent: 0; duokan-text-indent: 0; }
.feiye-author, .feiye-trans { font-family: "DK-KAITI", "Kaiti SC", serif; font-size: 1em; margin: 0.4em 0; text-indent: 0; duokan-text-indent: 0; }
.feiye-pub { font-size: 0.95em; margin-top: 5em; color: #666; text-indent: 0; duokan-text-indent: 0; }
"""
        (work_dir / "style.css").write_text(book_css, encoding='utf-8')
        print(f"[+] 抽取完成！生成中间稿：{work_dir / 'book.md'}")
        print(f"[+] 统计：插图总计 {len(image_files)} 张，提取并生成多看弹注 {total_footnotes_count} 条")


if __name__ == '__main__':
    main()
