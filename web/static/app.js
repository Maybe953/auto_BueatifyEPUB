/* -------------------------------------------------------------
   EPUB Auto-Beautifier Frontend Main Logic
------------------------------------------------------------- */

// 全局状态管理
const state = {
    fileId: null,
    tempFilePath: null,
    chapters: [],
    currentChapterIndex: 0,
    currentChapterPath: null,
    currentChapterContent: null,
    currentBaseHref: null,
    isUpdatingPreview: false,
    scrollLock: false
};

// DOM 元素引用
const DOM = {
    dropZone: document.getElementById('drop-zone'),
    fileInput: document.getElementById('file-input'),
    bookInfo: document.getElementById('book-info'),
    bookTitle: document.getElementById('book-title'),
    bookAuthor: document.getElementById('book-author'),
    btnReupload: document.getElementById('btn-reupload'),
    
    // 参数配置
    configPanel: document.getElementById('config-panel'),
    chkUseTemplate: document.getElementById('chk-use-template'),
    templateSelectGroup: document.getElementById('template-select-group'),
    selectTemplate: document.getElementById('select-template'),
    rangeLineHeight: document.getElementById('range-line-height'),
    valLineHeight: document.getElementById('val-line-height'),
    rangeMarginBottom: document.getElementById('range-margin-bottom'),
    valMarginBottom: document.getElementById('val-margin-bottom'),
    chkConvert: document.getElementById('chk-convert'),
    btnExport: document.getElementById('btn-export'),
    exportLoader: document.getElementById('export-loader'),
    
    // 高级清洗开关
    advancedSettingsWrapper: document.getElementById('advanced-settings-wrapper'),
    btnToggleAdvanced: document.getElementById('btn-toggle-advanced'),
    chkCleanStyles: document.getElementById('chk-clean-styles'),
    chkCleanContainers: document.getElementById('chk-clean-containers'),
    chkRemoveEmpty: document.getElementById('chk-remove-empty'),
    chkDetectTitles: document.getElementById('chk-detect-titles'),
    chkPageBreak: document.getElementById('chk-page-break'),
    chkWrapImages: document.getElementById('chk-wrap-images'),
    
    // 预览
    previewPlaceholder: document.getElementById('preview-placeholder'),
    previewContainer: document.getElementById('preview-container'),
    chapterWrapper: document.getElementById('chapter-wrapper'),
    chapterSelect: document.getElementById('chapter-select'),
    iframeOriginal: document.getElementById('iframe-original'),
    iframeBeautified: document.getElementById('iframe-beautified'),
    chkSyncScroll: document.getElementById('chk-sync-scroll'),
    
    // 弹窗
    downloadModal: document.getElementById('download-modal'),
    btnModalDownload: document.getElementById('btn-modal-download'),
    btnModalClose: document.getElementById('btn-modal-close'),
    progressModal: document.getElementById('progress-modal'),
    progressBarFill: document.getElementById('progress-bar-fill'),
    progressPercent: document.getElementById('progress-percent'),
    progressStatus: document.getElementById('progress-status')
};

// 初始化分段选择器逻辑 (首行缩进、适配设备)
const segments = {
    indent: { active: '2em', buttons: document.querySelectorAll('#indent-segmented .seg-btn') },
    device: { active: 'duokan', buttons: document.querySelectorAll('#device-segmented .seg-btn') }
};

// 字体配置状态
const fontState = {
    active: 'serif',
    customFont: null,
    select: document.getElementById('select-font')
};

// 绑定分段选择器事件
Object.keys(segments).forEach(key => {
    segments[key].buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            segments[key].buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            segments[key].active = btn.dataset.value;
            triggerPreviewUpdate(); // 配置变动, 触发预览刷新
        });
    });
});

// 动态拉取服务器可用字体列表与事件绑定
async function loadAvailableFonts() {
    const fontSelect = document.getElementById('select-font');
    if (!fontSelect) return;
    
    fontState.select = fontSelect;
    
    // 将 change 事件绑定迁移至此，确保 DOM 元素存在时方可绑定
    fontSelect.addEventListener('change', () => {
        const selectedOpt = fontSelect.options[fontSelect.selectedIndex];
        const isCustom = selectedOpt.getAttribute('data-custom') === 'true';
        
        if (isCustom) {
            fontState.active = 'serif';  // 降级 fallback
            fontState.customFont = selectedOpt.value;
        } else {
            fontState.active = selectedOpt.value;
            fontState.customFont = null;
        }
        triggerPreviewUpdate(); // 配置变动, 触发预览刷新
    });

    try {
        const res = await fetch('/api/fonts');
        const data = await res.json();
        if (data.success && data.fonts) {
            // 保留前两个系统字体 (系统宋体、系统无衬线)
            while (fontSelect.options.length > 2) {
                fontSelect.remove(2);
            }
            // 填充获取到的字体文件
            data.fonts.forEach(font => {
                const opt = document.createElement('option');
                opt.value = font.filename;
                opt.textContent = font.name;
                opt.setAttribute('data-custom', 'true');
                fontSelect.appendChild(opt);
            });
        }
    } catch (err) {
        console.error("拉取字体库失败:", err);
    }
}

// 自动根据页面 DOM 状态进行无缝加载
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        loadAvailableFonts();
        loadAvailableTemplates();
        initAdvancedSettings();
        initTemplateEvents();
    });
} else {
    loadAvailableFonts();
    loadAvailableTemplates();
    initAdvancedSettings();
    initTemplateEvents();
}

async function loadAvailableTemplates() {
    if (!DOM.selectTemplate) return;
    
    try {
        const res = await fetch('/api/templates');
        const data = await res.json();
        if (data.success && data.templates) {
            DOM.selectTemplate.innerHTML = '';
            if (data.templates.length === 0) {
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = '暂无可用模板 (请在 example/ 放置 EPUB)';
                DOM.selectTemplate.appendChild(opt);
            } else {
                data.templates.forEach(tpl => {
                    const opt = document.createElement('option');
                    opt.value = tpl.filename;
                    opt.textContent = tpl.title;
                    DOM.selectTemplate.appendChild(opt);
                });
            }
        }
    } catch (err) {
        console.error("拉取模板列表失败:", err);
    }
}

function initTemplateEvents() {
    if (DOM.chkUseTemplate) {
        DOM.chkUseTemplate.addEventListener('change', () => {
            const useTemplate = DOM.chkUseTemplate.checked;
            if (useTemplate) {
                DOM.templateSelectGroup.style.display = 'block';
                toggleFineTuneControls(true);
            } else {
                DOM.templateSelectGroup.style.display = 'none';
                toggleFineTuneControls(false);
            }
            triggerPreviewUpdate();
        });
    }

    if (DOM.selectTemplate) {
        DOM.selectTemplate.addEventListener('change', () => {
            triggerPreviewUpdate();
        });
    }
}

function toggleFineTuneControls(disabled) {
    const controls = [
        DOM.rangeLineHeight,
        DOM.rangeMarginBottom,
        document.getElementById('select-font'),
        document.getElementById('indent-segmented'),
        document.getElementById('device-segmented')
    ];
    
    controls.forEach(ctrl => {
        if (!ctrl) return;
        if (disabled) {
            ctrl.style.opacity = '0.4';
            ctrl.style.pointerEvents = 'none';
            if (ctrl.tagName === 'INPUT' || ctrl.tagName === 'SELECT') {
                ctrl.disabled = true;
            } else {
                ctrl.querySelectorAll('button').forEach(b => b.disabled = true);
            }
        } else {
            ctrl.style.opacity = '1';
            ctrl.style.pointerEvents = 'auto';
            if (ctrl.tagName === 'INPUT' || ctrl.tagName === 'SELECT') {
                ctrl.disabled = false;
            } else {
                ctrl.querySelectorAll('button').forEach(b => b.disabled = false);
            }
        }
    });
}

function initAdvancedSettings() {
    // 绑定高级排版清洗控制面板折叠展开
    if (DOM.btnToggleAdvanced) {
        DOM.btnToggleAdvanced.addEventListener('click', () => {
            DOM.advancedSettingsWrapper.classList.toggle('expanded');
        });
    }

    // 绑定高级排版开关变动以触发实时预览刷新
    const advSwitches = [
        DOM.chkCleanStyles,
        DOM.chkCleanContainers,
        DOM.chkRemoveEmpty,
        DOM.chkDetectTitles,
        DOM.chkPageBreak,
        DOM.chkWrapImages
    ];
    advSwitches.forEach(sw => {
        if (sw) {
            sw.addEventListener('change', () => {
                triggerPreviewUpdate();
            });
        }
    });
}

/* -------------------------------------------------------------
   拖拽文件上传逻辑
------------------------------------------------------------- */

// 点击上传区触发文件选择
DOM.dropZone.addEventListener('click', (e) => {
    // 避免点击重新上传按钮时触发选择文件
    if (e.target.closest('#btn-reupload')) return;
    DOM.fileInput.click();
});

DOM.fileInput.addEventListener('change', () => {
    if (DOM.fileInput.files.length > 0) {
        handleUpload(DOM.fileInput.files[0]);
    }
});

// 拖拽悬停效果
DOM.dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    DOM.dropZone.classList.add('dragover');
});

DOM.dropZone.addEventListener('dragleave', () => {
    DOM.dropZone.classList.remove('dragover');
});

DOM.dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    DOM.dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
        handleUpload(e.dataTransfer.files[0]);
    }
});

// 重新上传按钮
DOM.btnReupload.addEventListener('click', (e) => {
    e.stopPropagation();
    resetUploader();
});

// 触发文件上传接口
async function handleUpload(file) {
    if (!file.name.endsWith('.epub')) {
        alert('只支持处理 .epub 格式的电子书！');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    // 修改上传状态 UI
    const dragContent = DOM.dropZone.querySelector('.drag-content');
    const originalHTML = dragContent.innerHTML;
    dragContent.innerHTML = `
        <div class="loader"></div>
        <h3 style="margin-top: 1rem;">正在解析书籍结构...</h3>
        <p class="subtitle">请稍后，正在提取预览章节</p>
    `;

    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        if (data.success) {
            state.fileId = data.file_id;
            state.tempFilePath = data.temp_file_path;
            state.chapters = data.spine_paths;
            
            // 展示书籍详情
            showBookUploaded(data.title, data.creator);
            
            // 激活配置面板
            DOM.configPanel.classList.remove('disabled');
            DOM.btnExport.removeAttribute('disabled');
            
            // 载入章节下拉框
            renderChapterSelector();

            // 显示双栏预览区
            DOM.previewPlaceholder.style.display = 'none';
            DOM.previewContainer.style.display = 'grid';
            
            // 首次展示第一章
            if (state.chapters.length > 0) {
                DOM.chapterSelect.value = state.chapters[0];
                loadChapterByPath(state.chapters[0]);
            }
        } else {
            alert('上传解析失败: ' + (data.detail || '未知原因'));
            dragContent.innerHTML = originalHTML;
        }
    } catch (err) {
        console.error(err);
        alert('上传请求出错，请确保本地 Python 后端正常运行。');
        dragContent.innerHTML = originalHTML;
    }
}

function showBookUploaded(title, author) {
    DOM.dropZone.querySelector('.drag-content').style.display = 'none';
    DOM.bookTitle.textContent = title;
    DOM.bookAuthor.textContent = author;
    DOM.bookInfo.style.display = 'flex';
    DOM.dropZone.style.padding = '1rem 1.5rem';
}

function resetUploader() {
    state.tempFilePath = null;
    state.chapters = [];
    DOM.fileInput.value = '';
    
    DOM.bookInfo.style.display = 'none';
    DOM.dropZone.querySelector('.drag-content').style.display = 'flex';
    DOM.dropZone.style.padding = '2rem 1.5rem';
    
    // 禁用配置
    DOM.configPanel.classList.add('disabled');
    DOM.btnExport.setAttribute('disabled', 'true');
    
    // 隐藏预览
    DOM.chapterWrapper.style.display = 'none';
    DOM.previewPlaceholder.style.display = 'flex';
    DOM.previewContainer.style.display = 'none';
}

function renderChapterSelector() {
    DOM.chapterSelect.innerHTML = '';
    state.chapters.forEach((path, idx) => {
        const option = document.createElement('option');
        option.value = path;
        // 提取文件名简化显示名称
        const parts = path.split('/');
        const filename = parts[parts.length - 1];
        option.textContent = `[节 ${idx + 1}] ${filename}`;
        DOM.chapterSelect.appendChild(option);
    });
    DOM.chapterWrapper.style.display = 'inline-flex';
}

DOM.chapterSelect.addEventListener('change', (e) => {
    loadChapterByPath(e.target.value);
});

/* -------------------------------------------------------------
   加载章节与精排实时渲染 (按需加载 + 图片基准路径注入)
------------------------------------------------------------- */

async function loadChapterByPath(path) {
    if (!state.fileId || !path) return;
    
    // 打开临时加载等待字样
    DOM.iframeOriginal.srcdoc = "<h3 style='padding: 2rem; color: #6b7280; text-align:center;'>正在读取源电子书章节内容...</h3>";
    DOM.iframeBeautified.srcdoc = "<h3 style='padding: 2rem; color: #6b7280; text-align:center;'>正在进行样式实时排版清洗...</h3>";
    
    try {
        const res = await fetch(`/api/chapter?file_id=${state.fileId}&chapter_path=${encodeURIComponent(path)}`);
        const data = await res.json();
        
        if (data.success) {
            state.currentChapterPath = path;
            state.currentChapterContent = data.content;
            
            // 计算当前章节对应的 baseHref 路径，用于注入 <base> 标签完美加载图片
            const parts = path.split('/');
            parts.pop(); // 弹出文件名，留下相对目录
            const chapterDir = parts.join('/');
            state.currentBaseHref = `/temp_preview/${state.fileId}_unzipped/${chapterDir}/`;
            
            // 1. 灌入原始排版左侧 iframe (使用新渲染处理，避免嵌套 HTML 造成白屏)
            DOM.iframeOriginal.srcdoc = preparePreviewHtml(data.content, state.currentBaseHref, null);
            
            // 2. 调度精排预览
            updateBeautifyPreview();
            
            // 3. 注入滚动监听器
            setupSyncScroll();
        } else {
            alert("读取章节失败: " + data.detail);
        }
    } catch (err) {
        console.error("加载章节错误:", err);
        alert("网络异常，无法拉取该章节正文。");
    }
}

// 助手函数：整合基准 URL 注入与精排 CSS 内联注入，生成标准的不嵌套 XHTML 源码页面
function preparePreviewHtml(html, baseHref, cssContent) {
    let result = html;
    
    // 修正形如 src="/xxx" 或 href="/xxx" 导致绕过 <base> 标签向根域名发起请求的问题
    result = result.replace(/(src|href)=["']\/([^"']+)["']/g, '$1="$2"');
    
    // 1. 优先注入 baseHref，确保浏览器以最高的优先级解析所有资源基准路径
    if (baseHref) {
        const baseTag = `\n<base href="${baseHref}">\n`;
        if (result.includes('<head>')) {
            result = result.replace('<head>', `<head>${baseTag}`);
        } else if (result.includes('<HEAD>')) {
            result = result.replace('<HEAD>', `<HEAD>${baseTag}`);
        } else {
            if (result.includes('<html>')) {
                result = result.replace('<html>', `<html><head>${baseTag}</head>`);
            } else if (result.includes('<HTML>')) {
                result = result.replace('<HTML>', `<HTML><head>${baseTag}</head>`);
            }
        }
    }

    // 2. 如果后端直接返回了 CSS 内容，则直接以内联 <style> 硬编码嵌入！
    if (cssContent) {
        result = result.replace(/<link[^>]*global_style\.css[^>]*>/g, "");
        const styleTag = `\n<style type="text/css">\n/*<![CDATA[*/\n${cssContent}\n/*]]>*/\n</style>\n`;
        if (result.includes('</head>')) {
            result = result.replace('</head>', `${styleTag}</head>`);
        } else if (result.includes('</HEAD>')) {
            result = result.replace('</HEAD>', `${styleTag}</HEAD>`);
        }
    } else {
        const timestamp = new Date().getTime();
        result = result.replace(/global_style\.css/g, `global_style.css?v=${timestamp}`);
    }
    

    // 3. 移除开头的 XML 声明，极大地提升浏览器对 srcdoc 内联渲染的容错与兼容度，防止触发严苛的 XML Parse Error 白屏
    result = result.replace(/^<\?xml[^>]*\?>/i, "").trim();
    
    // 4. 注入多看弹注 Web 仿真器，实现开发期的本地可视化点击预览
    const popupSimulatorScript = `
    <style>
        .web-popup-simulator {
            position: absolute;
            z-index: 99999;
            background: #fff;
            border: 1px solid #ddd;
            border-radius: 8px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.2);
            padding: 16px;
            max-width: 85%;
            font-size: 15px;
            line-height: 1.6;
            color: #333;
            display: none;
            transition: opacity 0.2s;
            opacity: 0;
        }
        .web-popup-simulator::after {
            content: "";
            position: absolute;
            bottom: -6px;
            left: 20px;
            width: 12px;
            height: 12px;
            background: #fff;
            border-bottom: 1px solid #ddd;
            border-right: 1px solid #ddd;
            transform: rotate(45deg);
        }
    </style>
    <div id="web-popup-simulator" class="web-popup-simulator"></div>
    <script>
        document.addEventListener('click', function(e) {
            let a = e.target.closest('a');
            if(a && a.classList.contains('duokan-footnote')) {
                e.preventDefault();
                let href = a.getAttribute('href');
                let targetId = null;
                if(href) {
                    if(href.startsWith('#')) {
                        targetId = href.substring(1);
                    } else if(href.includes('#')) {
                        targetId = href.split('#')[1];
                    }
                }
                
                if(targetId) {
                    let targetLi = document.getElementById(targetId);
                    // 应对 _fast_convert_preview_footnotes 的特殊情况 (可能原始 ID 和注脚不一致)
                    if(!targetLi) targetLi = document.getElementById('note_' + targetId);
                    
                    if(targetLi) {
                        let popup = document.getElementById('web-popup-simulator');
                        let clone = targetLi.cloneNode(true);
                        let backLink = clone.querySelector('a');
                        if(backLink) backLink.remove(); 
                        popup.innerHTML = clone.innerHTML;
                        popup.style.display = 'block';
                        
                        let rect = a.getBoundingClientRect();
                        let topPos = window.scrollY + rect.top - popup.offsetHeight - 15;
                        if(topPos < 10) topPos = window.scrollY + rect.bottom + 15; 
                        
                        popup.style.top = topPos + 'px';
                        let leftPos = window.scrollX + rect.left - 20;
                        if(leftPos < 10) leftPos = 10; 
                        popup.style.left = leftPos + 'px';
                        
                        setTimeout(() => popup.style.opacity = '1', 10);
                        return;
                    } else {
                        // 如果当前 DOM 找不到注释目标，强制渲染一个临时的提示框（仅用于 Web 预览环境）
                        let popup = document.getElementById('web-popup-simulator');
                        popup.innerHTML = "<p>当前注释的实体内容在另一章 HTML 文件中 (ID: " + targetId + ")。<br>Web 预览器仅加载单章 DOM，因此无法在此跨页获取内容。<br><b>请放心，一键精排导出后的 EPUB 已启用跨章搬运，真机必定弹窗！</b></p>";
                        popup.style.display = 'block';
                        
                        let rect = a.getBoundingClientRect();
                        popup.style.top = (window.scrollY + rect.bottom + 15) + 'px';
                        popup.style.left = (window.scrollX + rect.left) + 'px';
                        setTimeout(() => popup.style.opacity = '1', 10);
                        return;
                    }
                }
            } else if (a && a.getAttribute('href') && a.getAttribute('href').includes('#')) {
                // 如果发现它是注释的格式但没被挂上 duokan-footnote，拦截它并弹窗警告
                let txt = a.innerText.trim();
                if (txt.match(/^\[?\d+\]?$/) || a.getAttribute('href').toLowerCase().includes('note')) {
                    e.preventDefault();
                    alert("检测到疑似注释链接，但前端解析时未被判定为弹注！href: " + a.getAttribute('href') + ", 文本: " + txt);
                }
            }
            let popup = document.getElementById('web-popup-simulator');
            if(popup && popup.style.opacity === '1' && !e.target.closest('#web-popup-simulator')) {
                popup.style.opacity = '0';
                setTimeout(() => popup.style.display = 'none', 200);
            }
        });
    </script>
    `;

    if (result.includes('</body>')) {
        result = result.replace('</body>', `\${popupSimulatorScript}</body>`);
    } else if (result.includes('</BODY>')) {
        result = result.replace('</BODY>', `\${popupSimulatorScript}</BODY>`);
    } else {
        result += popupSimulatorScript;
    }
    
    return result;
}

// 防抖定时器，避免滑块滑动时产生频繁的 HTTP 请求
let debounceTimer = null;
function triggerPreviewUpdate() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        updateBeautifyPreview();
    }, 150); // 150 毫秒延迟防抖
}

// 监听数值滑块变动
DOM.rangeLineHeight.addEventListener('input', (e) => {
    DOM.valLineHeight.textContent = e.target.value;
    triggerPreviewUpdate();
});

DOM.rangeMarginBottom.addEventListener('input', (e) => {
    DOM.valMarginBottom.textContent = e.target.value + 'em';
    triggerPreviewUpdate();
});

DOM.chkConvert.addEventListener('change', () => {
    triggerPreviewUpdate();
});

async function updateBeautifyPreview() {
    if (!state.tempFilePath || !state.currentChapterContent) return;
    
    state.isUpdatingPreview = true;
    
    const requestData = {
        temp_file_path: state.tempFilePath,
        line_height: parseFloat(DOM.rangeLineHeight.value),
        text_indent: segments.indent.active,
        margin_bottom: DOM.rangeMarginBottom.value + 'em',
        font_family: fontState.active,
        custom_font: fontState.customFont,
        convert_to_simplified: DOM.chkConvert.checked,
        target_device: segments.device.active,
        chapter_path: state.currentChapterPath,
        raw_html: state.currentChapterContent,
        // 模板排版选项
        use_template: DOM.chkUseTemplate ? DOM.chkUseTemplate.checked : false,
        template_filename: DOM.selectTemplate ? DOM.selectTemplate.value : null,
        // 高级清洗规则
        remove_empty_paragraphs: DOM.chkRemoveEmpty ? DOM.chkRemoveEmpty.checked : true,
        clean_inline_styles: DOM.chkCleanStyles ? DOM.chkCleanStyles.checked : true,
        clean_spans: DOM.chkCleanContainers ? DOM.chkCleanContainers.checked : true,
        clean_divs: DOM.chkCleanContainers ? DOM.chkCleanContainers.checked : true,
        auto_detect_titles: DOM.chkDetectTitles ? DOM.chkDetectTitles.checked : false,
        auto_page_break_h: DOM.chkPageBreak ? DOM.chkPageBreak.checked : false,
        wrap_images: DOM.chkWrapImages ? DOM.chkWrapImages.checked : false
    };

    try {
        const response = await fetch('/api/beautify_preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestData)
        });

        const data = await response.json();
        if (data.success) {
            // 样式已由后端直接覆盖写入临时目录下的 global_style.css，我们只需注入 base，通过原生的外链方式加载即可
            const styledHtml = preparePreviewHtml(data.beautified_html, state.currentBaseHref, data.css_content);
            DOM.iframeBeautified.srcdoc = styledHtml;
        }
    } catch (err) {
        console.error('精排刷新失败:', err);
    } finally {
        state.isUpdatingPreview = false;
    }
}

/* -------------------------------------------------------------
   左右 iframe 同步滚动逻辑 (带锁控制防死循环)
------------------------------------------------------------- */

function setupSyncScroll() {
    // 需在 iframe 加载完成后再绑定 scroll 事件
    DOM.iframeOriginal.onload = () => bindScroll(DOM.iframeOriginal, DOM.iframeBeautified);
    DOM.iframeBeautified.onload = () => bindScroll(DOM.iframeBeautified, DOM.iframeOriginal);
}

function bindScroll(sourceIframe, targetIframe) {
    const sourceWin = sourceIframe.contentWindow;
    if (!sourceWin) return;
    
    sourceWin.addEventListener('scroll', () => {
        if (!DOM.chkSyncScroll.checked) return;
        if (state.scrollLock) return; // 滚动锁触发, 避免死循环
        
        state.scrollLock = true;
        
        const sourceDoc = sourceIframe.contentDocument.documentElement;
        const targetDoc = targetIframe.contentDocument.documentElement;
        
        // 计算源 iframe 的滚动比例
        const totalHeight = sourceDoc.scrollHeight - sourceDoc.clientHeight;
        if (totalHeight > 0) {
            const scrollPercent = sourceDoc.scrollTop / totalHeight;
            // 映射到目标 iframe
            targetDoc.scrollTop = scrollPercent * (targetDoc.scrollHeight - targetDoc.clientHeight);
        }
        
        // 滚动结束释放锁
        setTimeout(() => {
            state.scrollLock = false;
        }, 30);
    });
}

/* -------------------------------------------------------------
   一键精排导出与弹窗下载
------------------------------------------------------------- */

DOM.btnExport.addEventListener('click', async () => {
    if (!state.tempFilePath) return;
    
    // 进入导出 loading 状态，并展现进度浮层
    DOM.btnExport.setAttribute('disabled', 'true');
    DOM.exportLoader.style.display = 'inline-block';
    DOM.btnExport.querySelector('.btn-content').style.opacity = '0.5';
    
    DOM.progressBarFill.style.width = '0%';
    DOM.progressPercent.textContent = '0%';
    DOM.progressStatus.textContent = '正在初始化排版服务...';
    DOM.progressModal.classList.add('show');
    
    const requestData = {
        temp_file_path: state.tempFilePath,
        line_height: parseFloat(DOM.rangeLineHeight.value),
        text_indent: segments.indent.active,
        margin_bottom: DOM.rangeMarginBottom.value + 'em',
        font_family: fontState.active,
        custom_font: fontState.customFont,
        convert_to_simplified: DOM.chkConvert.checked,
        target_device: segments.device.active,
        // 模板排版选项
        use_template: DOM.chkUseTemplate ? DOM.chkUseTemplate.checked : false,
        template_filename: DOM.selectTemplate ? DOM.selectTemplate.value : null,
        // 高级清洗规则
        remove_empty_paragraphs: DOM.chkRemoveEmpty ? DOM.chkRemoveEmpty.checked : true,
        clean_inline_styles: DOM.chkCleanStyles ? DOM.chkCleanStyles.checked : true,
        clean_spans: DOM.chkCleanContainers ? DOM.chkCleanContainers.checked : true,
        clean_divs: DOM.chkCleanContainers ? DOM.chkCleanContainers.checked : true,
        auto_detect_titles: DOM.chkDetectTitles ? DOM.chkDetectTitles.checked : false,
        auto_page_break_h: DOM.chkPageBreak ? DOM.chkPageBreak.checked : false,
        wrap_images: DOM.chkWrapImages ? DOM.chkWrapImages.checked : false
    };

    let pollInterval = null;

    try {
        const response = await fetch('/api/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestData)
        });

        const data = await response.json();
        if (data.success) {
            const taskId = data.task_id;
            
            // 开始开启定时轮询任务状态
            pollInterval = setInterval(async () => {
                try {
                    const statusRes = await fetch(`/api/export_status/${taskId}`);
                    const statusData = await statusRes.json();
                    
                    if (statusData.status === 'processing') {
                        DOM.progressBarFill.style.width = statusData.progress + '%';
                        DOM.progressPercent.textContent = statusData.progress + '%';
                        DOM.progressStatus.textContent = statusData.message;
                    } else if (statusData.status === 'success') {
                        clearInterval(pollInterval);
                        DOM.progressBarFill.style.width = '100%';
                        DOM.progressPercent.textContent = '100%';
                        DOM.progressStatus.textContent = '精排编译生成成功！';
                        
                        setTimeout(() => {
                            // 关闭进度弹窗
                            DOM.progressModal.classList.remove('show');
                            
                            // 展示成功弹窗
                            const savedFilename = statusData.result;
                            const successMsgNode = document.getElementById('export-success-message');
                            successMsgNode.innerHTML = `已完美为您重构排版并完成目标适配！<br><br>已直接保存至项目根目录，文件名为：<br><strong style="color: #a855f7; word-break: break-all; font-size: 1.1rem; display: block; margin-top: 0.5rem;">${savedFilename}</strong>`;
                            
                            DOM.downloadModal.classList.add('show');
                            resetExportButton();
                        }, 500);
                    } else if (statusData.status === 'failed') {
                        clearInterval(pollInterval);
                        DOM.progressModal.classList.remove('show');
                        alert(`精排失败：\n${statusData.message}`);
                        resetExportButton();
                    }
                } catch (pollErr) {
                    console.error('轮询导出进度失败:', pollErr);
                }
            }, 300); // 300ms 轮询间隔，体验佳且不增加后端负担

        } else {
            DOM.progressModal.classList.remove('show');
            alert('重排任务启动失败: ' + (data.detail || '未知原因'));
            resetExportButton();
        }
    } catch (err) {
        console.error(err);
        DOM.progressModal.classList.remove('show');
        alert('导出请求出错，请检查本地 Python 后端服务是否正常运行。');
        resetExportButton();
    }

    function resetExportButton() {
        DOM.btnExport.removeAttribute('disabled');
        DOM.exportLoader.style.display = 'none';
        DOM.btnExport.querySelector('.btn-content').style.opacity = '1';
    }
});

// 关闭弹窗
DOM.btnModalClose.addEventListener('click', () => {
    DOM.downloadModal.classList.remove('show');
});

// 点击弹窗外面同样关闭
DOM.downloadModal.addEventListener('click', (e) => {
    if (e.target === DOM.downloadModal) {
        DOM.downloadModal.classList.remove('show');
    }
});
