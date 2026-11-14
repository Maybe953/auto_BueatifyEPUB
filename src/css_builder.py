from src.config import BeautifyConfig

def build_beautified_css(config: BeautifyConfig, is_preview: bool = False, custom_font_url: str = None) -> str:
    """
    根据给定的排版配置, 构建出高兼容性且美观的标准排版 CSS 样式表。
    """
    # 构建自定义字体的 @font-face 声明
    font_face_declaration = ""
    if config.custom_font:
        font_format = "truetype"
        if config.custom_font.lower().endswith(".otf"):
            font_format = "opentype"
        elif config.custom_font.lower().endswith(".woff2"):
            font_format = "woff2"
            
        # 如果传入了特定的相对路径，优先使用它
        if custom_font_url:
            font_url = custom_font_url
        else:
            font_url = f"/fonts/{config.custom_font}" if is_preview else f"fonts/{config.custom_font}"
            
        font_face_declaration = f"""@font-face {{
    font-family: "CustomFont";
    src: url("{font_url}") format("{font_format}");
    font-weight: normal;
    font-style: normal;
}}

"""

    # 字体定义
    if config.custom_font:
        # 优先使用 CustomFont 自定义内嵌字体
        font_family_val = '"CustomFont", "Georgia", "STSong", "Songti SC", "SimSun", "Noto Serif CJK SC", "Source Han Serif SC", serif'
    elif config.font_family == "serif":
        # 衬线字：宋体/明体，适合小说与严肃阅读
        font_family_val = '"Georgia", "STSong", "Songti SC", "SimSun", "Noto Serif CJK SC", "Source Han Serif SC", serif'
    else:
        # 无衬线字：黑体/雅黑，适合现代文、说明文
        font_family_val = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", sans-serif'
        
    # 构建基础样式表
    css_content = f"""/* EPUB Auto-Beautifier Standard Style */
@page {{
    margin: 5% 4%;
}}

html, body {{
    margin: 0;
    padding: 0;
    background-color: #ffffff;
    color: #222222;
    font-family: {font_family_val} !important;
    line-height: {config.line_height} !important;
    text-align: justify;
    word-break: break-all;
    -webkit-font-smoothing: antialiased;
}}

/* 正文段落 */
p {{
    margin-top: 0 !important;
    margin-bottom: {config.margin_bottom} !important;
    text-indent: {config.text_indent};
    line-height: {config.line_height} !important;
    text-align: justify;
}}

/* 用于控制不缩进的段落(如诗歌、居中文字) */
p.no-indent, .no-indent p {{
    text-indent: 0 !important;
}}

/* 章节标题 */
h1, h2, h3, h4, h5, h6 {{
    font-family: {font_family_val};
    font-weight: bold;
    color: #111111;
    margin-top: 1.5em;
    margin-bottom: 0.8em;
    text-indent: 0 !important;
}}

h1, h2 {{
    text-align: center;
}}

h3, h4, h5, h6 {{
    text-align: left;
}}

h1 {{
    font-size: 1.5em;
    margin-top: 2.0em;
    margin-bottom: 1.2em;
    {"page-break-before: always; -epub-page-break-before: always;" if config.auto_page_break_h else ""}
}}

h2 {{
    font-size: 1.35em;
    {"page-break-before: always; -epub-page-break-before: always;" if config.auto_page_break_h else ""}
}}

h3 {{
    font-size: 1.2em;
}}

/* 文本对齐辅助类 (用于精准继承原书特意对齐样式) */
.align-center {{
    text-align: center !important;
}}
.align-left {{
    text-align: left !important;
}}
.align-right {{
    text-align: right !important;
}}

/* 引用块 */
blockquote {{
    margin: 1.2em 1.5em;
    padding-left: 0.8em;
    border-left: 3px solid #cccccc;
    color: #555555;
    font-style: normal;
}}

blockquote p {{
    text-indent: 0 !important;
    margin-bottom: 0.5em;
}}

/* 列表 */
ul, ol {{
    margin: 1em 0;
    padding-left: 2em;
}}

li {{
    margin-bottom: 0.4em;
}}

/* 图片与多媒体 */
div.img-container, p.img-container {{
    text-indent: 0 !important;
    text-align: center;
    margin: 1.2em 0;
}}

/* 封面专用全屏铺满容器样式：规避正文 margin 溢出，自适应各阅读器屏幕 */
div.cover-container {{
    text-indent: 0 !important;
    text-align: center;
    margin: 0 !important;
    padding: 0 !important;
    width: 100% !important;
    height: 100% !important;
}}

svg, image {{
    max-width: 100% !important;
    max-height: 100% !important;
}}

img {{
    max-width: 100%;
    height: auto;
    display: block;
    margin: 0 auto;
}}

span.img-caption, p.img-caption {{
    display: block;
    text-indent: 0 !important;
    text-align: center;
    font-size: 0.85em;
    color: #666666;
    margin-top: 0.5em;
}}

/* 分割线 */
hr {{
    border: none;
    border-top: 1px solid #dddddd;
    margin: 2em auto;
    width: 60%;
}}

/* 代码与行内高亮 */
code, pre {{
    font-family: "Courier New", Courier, monospace;
    background-color: #f6f6f6;
    font-size: 0.9em;
}}

pre {{
    display: block;
    padding: 0.8em;
    margin: 1em 0;
    overflow-x: auto;
    white-space: pre-wrap;
    word-wrap: break-word;
}}

/* 强调与加粗 */
strong, b {{
    font-weight: bold;
}}

em, i {{
    font-style: italic;
}}

/* 链接 */
a {{
    color: inherit;
    text-decoration: underline;
}}

/* 弹出式注释 (aside epub:type="footnote") 的优雅后备与降级显示样式 */
/* 兼容 KOReader, Kindle, Apple Books, Duokan 的标准书签 aside 样式 */
aside {{
    display: block;
    font-size: 0.85em;
    color: #555555;
    background-color: #fcfcfc;
    border-left: 3px solid #ff9900;
    margin: 1em 1.5em;
    padding: 0.5em 0.8em;
    text-indent: 0 !important;
}}
"""

    # 针对特定设备的专有优化
    if config.target_device == "duokan":
        # 多看专有优化：可注入针对多看强制分页的私有属性，提高翻页动画体验
        css_content += """
/* 多看阅读专有优化 */
h1, h2 {
    duokan-page-break-before: always;
}
"""
    elif config.target_device == "kindle":
        # Kindle 专有优化：去除可能导致 Kindle KF8 渲染异常的 CSS3 高级属性
        css_content += """
/* Kindle 专有优化 */
html, body {
    text-rendering: optimizeLegibility;
}
"""
    return font_face_declaration + css_content
