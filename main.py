import argparse
import sys
import os
import glob
import webbrowser
import uvicorn
from src.config import BeautifyConfig
from src.processor import EpubProcessor

def run_cli(args):
    """
    命令行模式运行电子书精排。
    """
    input_path = args.input
    output_path = args.output

    if not input_path or not output_path:
        print("错误: 命令行模式下必须指定输入和输出 EPUB 文件路径。")
        print("用法: python main.py <input_epub> <output_epub> [options]")
        print("或者启动 Web 预览服务: python main.py --web")
        sys.exit(1)

    print(f"[*] 开始精排电子书: {input_path}")
    
    # 探测模板路径
    template_path = None
    if args.template:
        if args.template == "DETECT":
            example_dir = os.path.join(os.getcwd(), "example")
            if os.path.exists(example_dir):
                epub_files = glob.glob(os.path.join(example_dir, "*.epub"))
                if epub_files:
                    epub_files.sort(key=os.path.getmtime, reverse=True)
                    template_path = epub_files[0]
                    print(f"[*] 自动探测到模板 EPUB: {template_path}")
                else:
                    print("[-] 错误: 在 example/ 目录下未找到任何 .epub 文件作为排版模板。")
                    sys.exit(1)
            else:
                print("[-] 错误: 未找到 example/ 目录，请创建该目录并放置模板 EPUB 电子书。")
                sys.exit(1)
        else:
            template_path = args.template
            if not os.path.exists(template_path):
                print(f"[-] 错误: 指定的模板文件不存在: {template_path}")
                sys.exit(1)

    config = BeautifyConfig(
        line_height=args.line_height,
        text_indent=args.indent,
        margin_bottom=args.margin,
        font_family=args.font,
        convert_to_simplified=args.convert,
        target_device=args.device
    )

    try:
        processor = EpubProcessor(config)
        if template_path:
            print(f"[*] 开启模板克隆模式，正在套用模板样式与排版特征: {template_path}")
            processor.beautify_epub_with_template(input_path, output_path, template_path)
        else:
            processor.beautify_epub(input_path, output_path)
        print(f"[+] 精排成功！已保存至: {output_path}")
    except Exception as e:
        print(f"[-] 精排失败: {str(e)}")
        sys.exit(1)

def run_web(port):
    """
    启动本地 Web 预览服务，并自动打开默认浏览器。
    """
    url = f"http://127.0.0.1:{port}"
    print(f"[*] 正在启动本地精排服务，请访问: {url}")
    
    # 延迟 1 秒在后台自动打开浏览器，防止服务尚未建立
    import threading
    import time
    def open_browser():
        time.sleep(1.2)
        print("[*] 正在为您自动打开精排控制台...")
        webbrowser.open(url)
        
    threading.Thread(target=open_browser, daemon=True).start()
    
    # 启动 Uvicorn 本地服务
    uvicorn.run("src.web_server:app", host="127.0.0.1", port=port, log_level="info")

def main():
    parser = argparse.ArgumentParser(description="EPUB Auto-Beautifier — 电子书快速精排工具")
    
    # 模式切换
    parser.add_argument("--web", action="store_true", help="启动本地可视化 Web 精排与实时预览服务")
    parser.add_argument("--port", type=int, default=8080, help="Web 服务的端口号 (默认 8080)")
    
    # 命令行精排参数
    parser.add_argument("input", nargs="?", help="待精排的原始 EPUB 文件路径")
    parser.add_argument("output", nargs="?", help="精排优化后的 EPUB 文件保存路径")
    
    # 模板套用选项
    parser.add_argument("--template", type=str, nargs="?", const="DETECT", default=None, help="基于模板 EPUB 样式的排版克隆。可指定具体模板路径，如果不指定路径但添加了 --template，则默认寻找根目录 example/ 目录下的模板 EPUB")
    
    # 排版微调选项
    parser.add_argument("--line-height", type=float, default=1.6, help="正文行高 (默认 1.6)")
    parser.add_argument("--indent", type=str, default="2em", help="正文段落首行缩进 (默认 2em)")
    parser.add_argument("--margin", type=str, default="0.5em", help="正文段后间距 (默认 0.5em)")
    parser.add_argument("--font", choices=["serif", "sans-serif"], default="serif", help="排版字体族: serif(宋体/衬线), sans-serif(黑体/无衬线)")
    parser.add_argument("--convert", action="store_true", help="是否自动进行繁体转简体中文")
    parser.add_argument("--device", choices=["duokan", "kindle"], default="duokan", help="目标排版适配平台: duokan(多看阅读), kindle(亚马逊Kindle)")

    args = parser.parse_args()

    if args.web:
        run_web(args.port)
    else:
        # 如果未加 --web 参数且未提供输入输出路径，则默认启动 Web UI 体验更佳
        if not args.input:
            print("[*] 未检测到命令行文件参数，默认为您启动可视化 Web 服务...")
            run_web(args.port)
        else:
            run_cli(args)

if __name__ == "__main__":
    main()
