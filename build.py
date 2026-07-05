import re

with open("deep-dive.md", "r", encoding="utf-8") as f:
    md = f.read()

# Convert to HTML paragraphs
lines = md.split("\n")
html_lines = []
in_code = False
in_list = False
code_lines = []

for line in lines:
    if line.startswith("```"):
        if in_code:
            html_lines.append(f"<pre>{''.join(code_lines)}</pre>")
            code_lines = []
            in_code = False
        else:
            in_code = True
        continue
    if in_code:
        code_lines.append(line + "\n")
        continue

    if line.startswith("# "):
        html_lines.append(f"<h1>{line[2:]}</h1>")
    elif line.startswith("## "):
        html_lines.append(f"<h2>{line[2:]}</h2>")
    elif line.startswith("### "):
        html_lines.append(f"<h3>{line[3:]}</h3>")
    elif line.startswith("> "):
        html_lines.append(f"<blockquote><p>{line[2:]}</p></blockquote>")
    elif line.startswith("- "):
        if not in_list:
            html_lines.append("<ul>")
            in_list = True
        html_lines.append(f"<li>{line[2:]}</li>")
    elif line.startswith("1. ") or line.startswith("2. ") or line.startswith("3. ") or line.startswith("4. "):
        if not in_list:
            html_lines.append("<ol>")
            in_list = True
        html_lines.append(f"<li>{line[3:]}</li>")
    elif line.startswith("|"):
        if not in_list and not html_lines[-1].startswith("<table"):
            html_lines.append("<table>")
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if all(c.startswith("---") for c in cells):
            continue
        tag = "th" if not any("<t" in h for h in html_lines[-3:]) else "td"
        html_lines.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
    else:
        if in_list:
            html_lines.append("</ul>" if "<ol>" not in html_lines[-1] else "</ol>")
            in_list = False
        if line.strip():
            line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
            line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', line)
            html_lines.append(f"<p>{line}</p>")
        else:
            html_lines.append("")

if in_list:
    html_lines.append("</ul>")
if in_code:
    html_lines.append(f"<pre>{''.join(code_lines)}</pre>")

body = "\n".join(html_lines)

page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>上下文压缩系统深度分析 — nankingjing</title>
<style>
:root{{--bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#58a6ff;--heading:#f0f6fc}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans SC',sans-serif;line-height:1.7;padding:0 16px}}
article{{max-width:780px;margin:0 auto;padding:48px 0 80px}}
h1{{font-size:1.8em;color:var(--heading);margin-bottom:8px}}
h2{{font-size:1.3em;color:var(--heading);margin:40px 0 16px;padding-bottom:6px;border-bottom:1px solid var(--border)}}
h3{{font-size:1.1em;color:var(--heading);margin:28px 0 12px}}
p{{margin-bottom:14px}}
pre{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 18px;overflow-x:auto;font-size:.85em;line-height:1.55;margin:14px 0;color:#c9d1d9}}
code{{font-family:'SF Mono',Consolas,monospace;font-size:.88em}}
:not(pre)>code{{background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:1px 5px;color:#d2a8ff}}
blockquote{{border-left:3px solid var(--accent);padding:8px 16px;margin:14px 0;color:var(--muted);background:var(--surface);border-radius:0 6px 6px 0}}
a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}
ul,ol{{margin:10px 0 10px 22px}}li{{margin-bottom:5px}}
table{{width:100%;border-collapse:collapse;margin:14px 0;font-size:.9em}}
th,td{{border:1px solid var(--border);padding:6px 12px;text-align:left}}
th{{background:var(--surface);color:var(--heading)}}
.back{{margin-bottom:24px;font-size:.9em}}
.footer{{margin-top:40px;padding-top:16px;border-top:1px solid var(--border);color:var(--muted);font-size:.85em}}
@media(max-width:600px){{article{{padding:24px 0 48px}}h1{{font-size:1.3em}}pre{{padding:10px 12px;font-size:.78em}}}}
</style>
</head>
<body>
<article>
<p class="back"><a href="./">&larr; 返回 Portfolio</a></p>
{body}
<div class="footer"><p><a href="https://github.com/nankingjing">nankingjing</a> &middot; 2026 &middot; All claims verifiable on GitHub</p></div>
</article>
</body>
</html>"""

with open("deep-dive.html", "w", encoding="utf-8") as f:
    f.write(page)
print("deep-dive.html created")
