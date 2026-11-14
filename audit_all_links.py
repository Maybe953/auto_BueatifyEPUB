import os
import re
from zipfile import ZipFile
from bs4 import BeautifulSoup

orig_epub = '讲谈社·日本的历史套装（全10册) (寺泽薫) (z-library.sk, 1lib.sk, z-lib.sk).epub'
new_epub = '讲谈社·日本的历史（全10册）_多看精排版.epub'

toc_files = {
    'text00000.html', 'text00004.html', 'text00024.html', 'text00042.html',
    'text00062.html', 'text00079.html', 'text00099.html', 'text00118.html',
    'text00140.html', 'text00159.html', 'text00178.html'
}

# 1. 扫描原书中所有正文内 cross-ref
orig_refs = []
with ZipFile(orig_epub) as z:
    for name in sorted(z.namelist()):
        fname = os.path.basename(name)
        if not fname.endswith('.html') or fname in toc_files or not fname.startswith('text'):
            continue
        soup = BeautifulSoup(z.read(name), 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            # 过滤注释与回跳
            if '#note' in href or 'footnote' in href:
                continue
            # 仅排除第二卷的 a01/b01 特殊注释
            if 'text00029' in fname and re.search(r'#[ab]0\d+$', href):
                continue
            if '#sigil_toc' in href:
                continue
            if href.startswith('http'):
                continue
            
            txt = a.get_text(strip=True)
            p_text = a.parent.get_text(strip=True) if a.parent else ""
            
            # 目标
            if '#' in href:
                t_f, t_id = href.split('#', 1)
                t_f = t_f if t_f else fname
            else:
                t_f, t_id = href, ""
            
            orig_refs.append({
                'src_file': fname,
                'link_text': txt,
                'href': href,
                'target_file': t_f,
                'target_id': t_id,
                'context': p_text[:60]
            })

print(f"原书正文内跨图表/章节真实交叉引用总数: {len(orig_refs)}")

# 2. 读取新 EPUB 的所有页面
with ZipFile(new_epub) as z_new:
    new_pages = {}
    for n in z_new.namelist():
        if n.endswith('.xhtml'):
            new_pages[os.path.basename(n)] = z_new.read(n).decode('utf-8')

matched = []
unmatched = []

for item in orig_refs:
    txt = item['link_text']
    t_f = item['target_file'].replace('.html', '')
    t_id = item['target_id']
    expected_aid = f"xref_{t_f}_{t_id}" if t_id else f"xref_{t_f}"
    
    found = False
    for p_name, p_html in new_pages.items():
        m = re.search(rf'<a [^>]*class="fig-ref"[^>]*href="([^"]*{expected_aid})"[^>]*>(.*?)</a>', p_html)
        if m:
            actual_href = m.group(1)
            actual_txt = m.group(2)
            
            tgt_file = actual_href.split('#')[0] or p_name
            tgt_id = actual_href.split('#')[1]
            tgt_exists = False
            if tgt_file in new_pages:
                tgt_exists = f'id="{tgt_id}"' in new_pages[tgt_file]
            
            matched.append({
                'orig': item,
                'src_page': p_name,
                'actual_href': actual_href,
                'actual_txt': actual_txt,
                'target_valid': tgt_exists
            })
            found = True
            break
            
    if not found:
        unmatched.append(item)

print(f"\n匹配统计:")
print(f"  成功匹配数: {len(matched)} / {len(orig_refs)}")
print(f"  未匹配数: {len(unmatched)}")

for m in matched:
    valid_flag = "√ 有效" if m['target_valid'] else "× 无效"
    print(f"[{valid_flag}] 原文 {m['orig']['src_file']} ({m['orig']['link_text']}) -> {m['orig']['href']}")
    print(f"         新版 {m['src_page']} -> {m['actual_href']}")

if unmatched:
    print("\n未匹配项列表:")
    for u in unmatched:
        print(f"  原文 {u['src_file']} -> {u['href']} ({u['link_text']}) | 上下文: {u['context']}")
