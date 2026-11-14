import os

class BeautifyConfig:
    def __init__(self, **kwargs):
        # 默认排版参数
        self.line_height = float(kwargs.get("line_height", 1.6))       # 行高
        self.text_indent = kwargs.get("text_indent", "2em")            # 首行缩进
        self.margin_bottom = kwargs.get("margin_bottom", "0.5em")      # 段后距
        self.font_family = kwargs.get("font_family", "serif")          # 字体类型: serif (衬线), sans-serif (无衬线)
        self.custom_font = kwargs.get("custom_font", None)             # 自定义内嵌字体文件名 (例如 LXGWWenKaiLite-Regular.ttf)
        self.convert_to_simplified = bool(kwargs.get("convert_to_simplified", False)) # 是否转换为简体中文
        
        # 核心清洗规则控制（默认开启标准清洗规则，以消除原书干扰排版）
        self.remove_empty_paragraphs = bool(kwargs.get("remove_empty_paragraphs", True)) # 移除多余空行
        self.clean_inline_styles = bool(kwargs.get("clean_inline_styles", True))         # 剥离原书行内样式
        self.clean_spans = bool(kwargs.get("clean_spans", True))                         # 移除冗余的 span 嵌套
        self.clean_divs = bool(kwargs.get("clean_divs", True))                           # 移除无语义的 div 嵌套
        self.auto_page_break_h = bool(kwargs.get("auto_page_break_h", False))             # 标题前是否强制分页
        self.auto_detect_titles = bool(kwargs.get("auto_detect_titles", False))           # 是否自动将识别到的段落标题转换为 h 标签
        self.wrap_images = bool(kwargs.get("wrap_images", False))                         # 是否重写没有容器包裹的图片标签

        # 目标设备偏好 (duokan 或 kindle)
        self.target_device = kwargs.get("target_device", "duokan")

    def to_dict(self):
        return {
            "line_height": self.line_height,
            "text_indent": self.text_indent,
            "margin_bottom": self.margin_bottom,
            "font_family": self.font_family,
            "custom_font": self.custom_font,
            "convert_to_simplified": self.convert_to_simplified,
            "remove_empty_paragraphs": self.remove_empty_paragraphs,
            "clean_inline_styles": self.clean_inline_styles,
            "clean_spans": self.clean_spans,
            "clean_divs": self.clean_divs,
            "auto_page_break_h": self.auto_page_break_h,
            "auto_detect_titles": self.auto_detect_titles,
            "wrap_images": self.wrap_images,
            "target_device": self.target_device,
        }

# 默认全局配置
DEFAULT_CONFIG = BeautifyConfig()
