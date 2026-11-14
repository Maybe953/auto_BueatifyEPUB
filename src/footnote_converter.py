import re
import os
from bs4 import BeautifulSoup
from typing import List, Dict

class FootnoteConverter:
    def __init__(self):
        pass

    def convert_footnotes(self, temp_dir: str, use_template: bool = False, icon_img_rel_path: str = None):
        from src.epub_parser import EpubParser
        parser = EpubParser()
        parser.parse(temp_dir)

        footnotes_map = {}
        for html_rel_path in parser.spine_paths:
            html_path = os.path.join(temp_dir, html_rel_path)
            if not os.path.exists(html_path):
                continue
            with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
                soup = BeautifulSoup(f.read(), "xml")
            
            anchors = soup.find_all("a", href=True)
            for a in anchors:
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if "#" in href:
                    target_file, target_id = href.split("#", 1)
                    if not target_file:
                        target_file = html_rel_path
                    else:
                        target_file = os.path.normpath(os.path.join(os.path.dirname(html_rel_path), target_file)).replace('\\', '/')
                    
                    if target_file not in footnotes_map:
                        footnotes_map[target_file] = {}
                    if target_id not in footnotes_map[target_file]:
                        footnotes_map[target_file][target_id] = []
                    
                    footnotes_map[target_file][target_id].append({
                        "src_html_path": html_path,
                        "text": text,
                        "id": target_id
                    })
        
        numeric_id_counter = 1
        for target_file, targets in footnotes_map.items():
            target_path = os.path.join(temp_dir, target_file)
            if not os.path.exists(target_path):
                continue
            
            with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                target_soup = BeautifulSoup(f.read(), "xml")

            for target_id, sources in targets.items():
                target_node = target_soup.find(id=target_id)
                if not target_node:
                    target_node = target_soup.find(attrs={"name": target_id})
                if not target_node:
                    continue
                
                if self._is_footnote_node(target_node, target_id, sources):
                    self._apply_footnote_transformation(
                        target_path=target_path, 
                        target_id=target_id, 
                        target_node=target_node, 
                        target_soup=target_soup, 
                        sources=sources, 
                        use_template=use_template, 
                        icon_img_rel_path=icon_img_rel_path,
                        numeric_id=numeric_id_counter
                    )
                    numeric_id_counter += 1

        print(f"[*] Footnote conversion complete: converted {numeric_id_counter - 1} footnotes across the book.")

    def _is_footnote_node(self, target_node, target_id: str, sources: List[dict]) -> bool:
        if target_node.name in ["body", "html", "head"]:
            return False

        if target_node.find("img") or target_node.name == "img":
            return False

        parent = target_node.parent
        if parent and (parent.find("img") or parent.name == "img"):
            return False

        target_text = target_node.get_text(strip=True)
        if parent:
            target_text += " " + parent.get_text(strip=True)
        if re.search(r'(?:图\s*\d+|插图|点击查看|大图|图片|图表)', target_text):
            return False

        id_lower = target_id.lower()
        if "back" in id_lower or "return" in id_lower:
            return False

        score = 0
        for src in sources:
            text = src["text"]
            if re.match(r'^(\[?\d+\]?|①|②|③|④|⑤|⑥|⑦|⑧|⑨|⑩|⑪|⑫|⑬|⑭|⑮|⑯|⑰|⑱|⑲|⑳|\*|\d+|\b(fn|note)\b.*)$', text):
                score += 3
            elif len(text) <= 4:
                score += 2
            elif len(text) > 10:
                score -= 4

        if any(x in id_lower for x in ["note", "fn", "footnote", "comment", "desc"]):
            score += 2
        
        pure_len = len(target_node.get_text(strip=True))
        if pure_len <= 350:
            score += 2
        elif pure_len > 600:
            score -= 5

        back_links = target_node.find_all("a", href=True)
        if parent:
            back_links = list(set(back_links + parent.find_all("a", href=True)))
            
        for bl in back_links:
            bl_href = bl["href"]
            if "#" in bl_href:
                bl_file, bl_id = bl_href.split("#", 1)
                if any(src["id"] == bl_id for src in sources) or "back" in bl_id.lower() or "note" in bl_id.lower():
                    score += 4
                    break

        return score >= 3

    def _apply_footnote_transformation(self, target_path: str, target_id: str, target_node, target_soup, sources: List[dict], use_template: bool = False, icon_img_rel_path: str = None, numeric_id: int = 1):
        note_text = target_node.get_text(strip=True)
        container = target_node
        if container.name in ["a", "span"]:
            parent = container.parent
            if parent and parent.name in ["p", "li", "div", "dd", "dt"]:
                container = parent
        
        target_copy = BeautifulSoup(str(target_node), "xml")
        for old_a in target_copy.find_all("a"):
            old_a.decompose()
        note_text = target_copy.get_text().strip()
        
        if not note_text and container:
            container_copy = BeautifulSoup(str(container), "xml")
            for old_a in container_copy.find_all("a"):
                old_a.decompose()
            note_text = container_copy.get_text().strip()

        new_target_id = f"note_{numeric_id}"
        new_src_id = f"noteref_{numeric_id}"

        if container and container.parent:
            container.decompose()
        
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(str(target_soup))

        src_groups = {}
        for src in sources:
            path = src["src_html_path"]
            if path not in src_groups:
                src_groups[path] = []
            src_groups[path].append(src)

        for src_path, items in src_groups.items():
            if not os.path.exists(src_path):
                continue
            with open(src_path, "r", encoding="utf-8", errors="ignore") as f:
                src_soup = BeautifulSoup(f.read(), "xml")

            if use_template:
                clean_note_text = re.sub(r'^\s*(?:\[\d+\]|\d+[\.\s]|①|②|③|④|⑤|⑥|⑦|⑧|⑨|⑩|\[注?\s*\d+\])\s*', '', note_text)
                if not clean_note_text:
                    clean_note_text = note_text if note_text else (sources[0]["text"] if sources else "注释详情")

                li_node = src_soup.new_tag("li", attrs={"class": "duokan-footnote-item", "id": new_target_id})
                p_node = src_soup.new_tag("p", attrs={"class": "footnote"})
                
                back_a = src_soup.new_tag("a", href=f"#{new_src_id}", style="text-decoration:none!important")
                back_a.string = "⊙ "
                p_node.append(back_a)
                    
                text_span = src_soup.new_tag("span")
                text_span.string = clean_note_text
                p_node.append(text_span)
                li_node.append(p_node)

                body = src_soup.find("body") or src_soup
                container_tag = body.find("aside", attrs={"epub:type": "footnote"})
                if not container_tag:
                    container_tag = src_soup.new_tag("aside", attrs={"epub:type": "footnote"})
                    body.append(container_tag)

                ol_tag = container_tag.find("ol", attrs={"class": "duokan-footnote-content"})
                if not ol_tag:
                    container_tag.clear()
                    hr_div = src_soup.new_tag("div")
                    hr_tag = src_soup.new_tag("hr", attrs={"class": "xian"})
                    hr_div.append(hr_tag)
                    container_tag.append(hr_div)
                    
                    ol_tag = src_soup.new_tag("ol", attrs={"class": "duokan-footnote-content"})
                    container_tag.append(ol_tag)

                for old_child in list(ol_tag.children):
                    if hasattr(old_child, "get") and old_child.get("id") == new_target_id:
                        old_child.decompose()

                ol_tag.append(li_node)
            else:
                body = src_soup.find("body") or src_soup
                container_tag = body.find("aside", attrs={"epub:type": "footnote", "id": new_target_id})
                if not container_tag:
                    container_tag = src_soup.new_tag("aside", attrs={"epub:type": "footnote", "id": new_target_id, "class": "duokan-footnote-item"})
                    p_node = src_soup.new_tag("p")
                    p_node.string = note_text
                    container_tag.append(p_node)
                    body.append(container_tag)

            modified = False
            for item in items:
                target_matched = False
                anchors = src_soup.find_all("a", href=True)
                for a in anchors:
                    if a.find_parent("aside"):
                        continue
                        
                    if target_id in a["href"] or (item["text"] and item["text"] in a.get_text(strip=True)):
                        a["epub:type"] = "noteref"
                        a["class"] = ["duokan-footnote"]
                        a["style"] = "text-decoration:none!important;color:black;"
                        a["href"] = f"#{new_target_id}"
                        a["id"] = new_src_id
                        
                        if use_template and icon_img_rel_path:
                            a.string = ""
                            span_img = src_soup.new_tag("span", attrs={"class": "koboSpan"})
                            img_tag = src_soup.new_tag("img", alt="note", src=icon_img_rel_path)
                            span_img.append(img_tag)
                            a.append(span_img)
                        else:
                            orig_txt = a.get_text(strip=True)
                            if not orig_txt or orig_txt == "":
                                num_m = re.search(r'\d+', target_id)
                                orig_txt = f"[{num_m.group(0)}]" if num_m else f"[{numeric_id}]"
                            a.string = orig_txt
                        modified = True
                        target_matched = True

                if not target_matched:
                    num_match = re.search(r'\d+', target_id)
                    num_str = num_match.group(0) if num_match else ""
                    pattern = rf'(\[{num_str}\]|①|②|③|④|⑤|⑥|⑦|⑧|⑨|⑩|\[注?\s*{num_str}\])' if num_str else r'(\[\d+\]|①|②|③|④|⑤|⑥|⑦|⑧|⑨|⑩)'
                    
                    for p in src_soup.find_all(["p", "sup", "span"]):
                        if re.search(pattern, p.get_text()):
                            for child in list(p.children):
                                child_txt = child.get_text().strip() if hasattr(child, "get_text") else str(child).strip()
                                m = re.search(pattern, child_txt)
                                if m:
                                    new_a = src_soup.new_tag("a", href=f"#{new_target_id}", attrs={
                                        "class": "duokan-footnote",
                                        "epub:type": "noteref",
                                        "id": new_src_id,
                                        "style": "text-decoration:none!important;color:black;"
                                    })
                                    if use_template and icon_img_rel_path:
                                        span_img = src_soup.new_tag("span", attrs={"class": "koboSpan"})
                                        img_tag = src_soup.new_tag("img", alt="note", src=icon_img_rel_path)
                                        span_img.append(img_tag)
                                        new_a.append(span_img)
                                    else:
                                        new_a.string = m.group(1)
                                    child.replace_with(new_a)
                                    modified = True
                                    target_matched = True
                                    break
                        if target_matched:
                            break

            html_node = src_soup.find("html")
            if html_node:
                html_node["xmlns:epub"] = "http://www.idpf.org/2007/ops"

            if modified or use_template:
                with open(src_path, "w", encoding="utf-8") as f:
                    f.write(str(src_soup))
