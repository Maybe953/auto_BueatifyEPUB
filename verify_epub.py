from zipfile import ZipFile
import re

epub = '讲谈社·日本的历史（全10册）_多看精排版.epub'
with ZipFile(epub) as z:
    count = 0
    abnormal = []
    samples = []
    for name in z.namelist():
        if name.endswith('.xhtml'):
            txt = z.read(name).decode('utf-8')
            for m in re.finditer(r'<a class="fig-backref"[^>]*>(.*?)</a>', txt):
                count += 1
                link_text = m.group(1)
                full_tag = m.group(0)
                if link_text != '[返回正文]':
                    abnormal.append((name, full_tag))
                if len(samples) < 5:
                    samples.append(full_tag)

    print(f'Total backref tags found: {count}')
    print(f'Abnormal backref tags: {len(abnormal)}')
    for s in samples:
        print('Sample tag:', s)
