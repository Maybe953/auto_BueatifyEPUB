import os
import sys
import urllib.request
import ssl
import time

# 修正并采用稳定高速的 gcore.jsdelivr.net 镜像直链
FONTS_TO_DOWNLOAD = [
    {
        "name": "霞鹜文楷 Lite",
        "filename": "LXGWWenKaiLite-Regular.ttf",
        "url": "https://gcore.jsdelivr.net/gh/lxgw/LxgwWenKai-Lite@v1.522/fonts/TTF/LXGWWenKaiLite-Regular.ttf"
    },
    {
        "name": "霞鹜文楷 GB",
        "filename": "LXGWWenKaiGB-Regular.ttf",
        "url": "https://gcore.jsdelivr.net/gh/lxgw/LxgwWenkaiGB@v1.010/fonts/TTF/LXGWWenKaiGB-Regular.ttf"
    },
    {
        "name": "霞鹜文楷 TC",
        "filename": "LXGWWenKaiTC-Regular.ttf",
        "url": "https://gcore.jsdelivr.net/gh/lxgw/LxgwWenkaiTC@v1.010/fonts/TTF/LXGWWenKaiTC-Regular.ttf"
    },
    {
        "name": "仓耳今楷",
        "filename": "TsangerJinKai01-W03.ttf",
        "url": "https://gcore.jsdelivr.net/gh/ZanshinS/Obsidian-Settings/Fonts/TsangerJinKai01-W03.ttf"
    }
]

def download_progress(block_num, block_size, total_size):
    """
    实时的下载进度回调条
    """
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(100, int(downloaded * 100 / total_size))
        # 换算为 MB
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        sys.stdout.write(f"\r  [下载中...] {percent}% | {downloaded_mb:.1f} MB / {total_mb:.1f} MB")
        sys.stdout.flush()
    else:
        sys.stdout.write(f"\r  [下载中...] {downloaded / 1024:.1f} KB")
        sys.stdout.flush()

def main():
    fonts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fonts"))
    os.makedirs(fonts_dir, exist_ok=True)
    
    print("===================================================")
    print("     EPUB Auto-Beautifier 字体自动下载工具")
    print(f"     目标保存目录: {fonts_dir}")
    print("===================================================\n")
    
    # 限制 TLS 版本并跳过证书验证以保证最大兼容性
    context = ssl._create_unverified_context()
    try:
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    except AttributeError:
        pass
        
    for font in FONTS_TO_DOWNLOAD:
        dest_path = os.path.join(fonts_dir, font["filename"])
        print(f"[*] 准备下载: {font['name']} ({font['filename']})")
        print(f"    源链接: {font['url']}")
        
        # 如果文件已存在且大小大于 1MB，则跳过
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1024 * 1024:
            print(f"[+] 字体文件已存在，跳过下载。\n")
            continue
            
        try:
            start_time = time.time()
            # 加上 User-Agent 伪装
            req = urllib.request.Request(
                font["url"], 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            
            # 使用 urlopen 读取并写入，代替 urllib.request.urlretrieve (支持 ssl context)
            with urllib.request.urlopen(req, context=context, timeout=30) as response:
                total_size = int(response.getheader('Content-Length', 0))
                downloaded = 0
                block_size = 1024 * 64
                
                with open(dest_path, 'wb') as out_file:
                    block_num = 0
                    while True:
                        block = response.read(block_size)
                        if not block:
                            break
                        out_file.write(block)
                        downloaded += len(block)
                        block_num += 1
                        download_progress(block_num, block_size, total_size)
                        
            duration = time.time() - start_time
            sys.stdout.write("\n")
            print(f"[+] {font['name']} 下载成功！耗时: {duration:.1f} 秒\n")
        except Exception as e:
            sys.stdout.write("\n")
            print(f"[-] 下载失败: {str(e)}")
            # 清理可能产生的半截脏文件
            if os.path.exists(dest_path):
                os.remove(dest_path)
            print("    注意: 请检查您的网络连接并重试。\n")

    print("[*] 所有字体下载及检查完毕！")

if __name__ == "__main__":
    main()
