import zipfile
import re
from pathlib import Path
from bs4 import BeautifulSoup
import warnings
warnings.filterwarnings("ignore")

def analyze_epub(path):
    info = {
        "path": path,
        "files_count": 0,
        "images_count": 0,
        "spine_count": 0,
        "spine_titles": [],
        "toc_titles": [],
        "broken_footnotes": [],
        "kaiti_chapters": [],
        "fullscreen_pages": [],
        "theme_colors": [],
        "has_title_page": False,
    }
    
    with zipfile.ZipFile(path, 'r') as z:
        namelist = z.namelist()
        info["files_count"] = len(namelist)
        info["images_count"] = len([n for n in namelist if any(n.lower().endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp'))])
        info["has_title_page"] = 'OEBPS/Text/title.xhtml' in namelist
        
        # OPF & Spine
        opf_name = next(n for n in namelist if n.endswith('.opf'))
        soup_opf = BeautifulSoup(z.read(opf_name), 'xml')
        id_href = {it['id']: it['href'] for it in soup_opf.find_all('item')}
        spine_itemrefs = soup_opf.find('spine').find_all('itemref')
        spine = [it['idref'] for it in spine_itemrefs]
        info["spine_count"] = len(spine)
        for it in spine_itemrefs:
            if 'duokan-page-fullscreen' in it.get('properties', ''):
                info["fullscreen_pages"].append(it['idref'])
        
        # TOC
        ncx_name = next((n for n in namelist if n.endswith('.ncx')), None)
        if ncx_name:
            soup_ncx = BeautifulSoup(z.read(ncx_name), 'xml')
            info["toc_titles"] = [nav.find('text').text.strip() for nav in soup_ncx.find_all('navPoint') if nav.find('text')]
            
        # Analyze each spine document
        for sid in spine:
            href = id_href.get(sid, '')
            full_path = 'OEBPS/' + href if not href.startswith('OEBPS/') else href
            if not href.endswith(('.xhtml', '.html')):
                continue
            html_content = z.read(full_path).decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html_content, 'html.parser')
            
            t = soup.find('title').text.strip() if soup.find('title') else ''
            info["spine_titles"].append((href, t))
            
            # Check kaiti-body
            body = soup.find('body')
            if body and 'kaiti-body' in body.get('class', []):
                info["kaiti_chapters"].append((href, t))
                
            # Check fullscreen
            divs = soup.find_all('div')
            for d in divs:
                cls = d.get('class', [])
                if 'duokan-page-fullscreen' in cls:
                    info["fullscreen_pages"].append((href, t))
                    break
                    
            # Check broken footnotes: <a class="duokan-footnote"...></p>
            for a in soup.find_all('a', class_=lambda c: c and 'duokan-footnote' in c):
                p = a.find_parent('p')
                if p:
                    children = [c for c in p.children if str(c).strip()]
                    if children and a == children[-1]:
                        next_p = p.find_next_sibling('p')
                        if next_p:
                            next_text = next_p.text.strip()
                            if next_text and next_text[0] in '）)）、，。！？!?;；：:':
                                info["broken_footnotes"].append((href, next_text[:30]))
                            
        # CSS Theme Check
        css_name = next((n for n in namelist if n.endswith('style.css')), None)
        if css_name:
            css_text = z.read(css_name).decode('utf-8', errors='ignore')
            if '#146eb4' in css_text:
                info["theme_colors"].append('#146eb4 (学术蓝)')
            if '#a08a6a' in css_text:
                info["theme_colors"].append('#a08a6a (多看经典棕金)')

    return info

def compare_epubs(ref_path, target_path):
    print("=" * 70)
    print("  EPUB 深度对比校验报告")
    print(f"  基准标杆 (Ref):   {ref_path}")
    print(f"  待验目标 (Target): {target_path}")
    print("=" * 70)
    
    ref = analyze_epub(ref_path)
    tgt = analyze_epub(target_path)
    
    print("\n【1. 页面与媒体资产概况】")
    print(f"  - 总文件数:  Ref={ref['files_count']}  |  Target={tgt['files_count']}  (差值: {tgt['files_count'] - ref['files_count']})")
    print(f"  - 插图总数:  Ref={ref['images_count']}  |  Target={tgt['images_count']}  (差值: {tgt['images_count'] - ref['images_count']})")
    print(f"  - 阅读脊(Spine)总页数: Ref={ref['spine_count']}  |  Target={tgt['spine_count']}  (差值: {tgt['spine_count'] - ref['spine_count']})")
    print(f"  - 独立书名页 (title.xhtml): Ref={'有' if ref['has_title_page'] else '无'} | Target={'有' if tgt['has_title_page'] else '无'}")
    print(f"  - 全屏彩图页数 (Fullscreen): Ref={len(ref['fullscreen_pages'])} | Target={len(tgt['fullscreen_pages'])}")
    
    print("\n【2. 注释行内嵌合完整性（断行/截断检测）】")
    print(f"  - 异常截断注标段落数: Ref={len(ref['broken_footnotes'])} | Target={len(tgt['broken_footnotes'])}")
    if tgt['broken_footnotes']:
        print("    [!] 目标版本存在断行截断的注脚示例 (前 5 处):")
        for h, snippet in tgt['broken_footnotes'][:5]:
            print(f"        * 页面 {h}: ...断开后接「{snippet}」")
            
    print("\n【3. 全篇楷体 (kaiti-body) 误伤检测】")
    print(f"  - Ref 楷体章节数:   {len(ref['kaiti_chapters'])}")
    print(f"  - Target 楷体章节数: {len(tgt['kaiti_chapters'])}")
    if tgt['kaiti_chapters']:
        print("    Target 楷体章节列表:")
        for h, t in tgt['kaiti_chapters']:
            print(f"        * {h}: {t}")
            
    print("\n【4. 视觉主题色】")
    print(f"  - Ref 主题色:   {', '.join(ref['theme_colors'])}")
    print(f"  - Target 主题色: {', '.join(tgt['theme_colors'])}")

    print("\n【5. 目录与分卷缺失比对】")
    ref_toc_set = set(ref['toc_titles'])
    tgt_toc_set = set(tgt['toc_titles'])
    missing_in_tgt = [t for t in ref['toc_titles'] if t not in tgt_toc_set]
    extra_in_tgt = [t for t in tgt['toc_titles'] if t not in ref_toc_set]
    print(f"  - Ref TOC 目录条目数:    {len(ref['toc_titles'])}")
    print(f"  - Target TOC 目录条目数: {len(tgt['toc_titles'])}")
    if missing_in_tgt:
        print(f"  - 目标版本缺失的目录项 ({len(missing_in_tgt)} 项):")
        for m in missing_in_tgt[:10]:
            print(f"        * 缺失: {m}")
    if extra_in_tgt:
        print(f"  - 目标版本多出的目录项 ({len(extra_in_tgt)} 项):")
        for e in extra_in_tgt[:10]:
            print(f"        * 多出: {e}")

    print("=" * 70)
    passed = (
        ref['spine_count'] == tgt['spine_count'] and
        len(tgt['broken_footnotes']) == 0 and
        len(tgt['kaiti_chapters']) == len(ref['kaiti_chapters']) and
        len(missing_in_tgt) == 0
    )
    if passed:
        print("  【比对判定】： 100% 对齐成功！已达到标杆基准品质！")
    else:
        print("  【比对判定】： 存在未对齐差异项，需继续优化通用程序。")
    print("=" * 70)

if __name__ == '__main__':
    import sys
    ref = sys.argv[1] if len(sys.argv) > 1 else '讲谈社·日本的历史（全10册）_多看精排版.epub'
    target = sys.argv[2] if len(sys.argv) > 2 else '讲谈社·日本的历史套装（全10册）_多看精排版.epub'
    compare_epubs(ref, target)
