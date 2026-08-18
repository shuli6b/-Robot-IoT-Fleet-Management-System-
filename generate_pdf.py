import markdown
import os
import subprocess
import time

md_file = r"D:\Antigravity projects\机器人管理系统\huashu_bridge\华数Ⅲ型机器人现场接入与联调指引.md"
html_file = r"C:\Users\32755\Desktop\华数Ⅲ型机器人现场接入与联调指引.html"
pdf_file = r"C:\Users\32755\Desktop\华数Ⅲ型机器人现场接入与联调指引.pdf"

with open(md_file, "r", encoding="utf-8") as f:
    text = f.read()

# Add basic CSS to make tables look good
html = markdown.markdown(text, extensions=['tables', 'fenced_code'])
styled_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; line-height: 1.6; padding: 20px; max-width: 900px; margin: 0 auto; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background-color: #f2f2f2; }}
    code {{ background-color: #f5f5f5; padding: 2px 4px; border-radius: 4px; font-family: Consolas, monospace; }}
    pre {{ background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; }}
    pre code {{ background-color: transparent; padding: 0; }}
</style>
</head>
<body>
{html}
</body>
</html>
"""

with open(html_file, "w", encoding="utf-8") as f:
    f.write(styled_html)

print("HTML generated, converting to PDF...")
edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
subprocess.run([edge_path, "--headless", "--disable-gpu", f"--print-to-pdf={pdf_file}", html_file])

# Cleanup HTML
if os.path.exists(html_file):
    os.remove(html_file)

print(f"PDF generated successfully at {pdf_file}")
