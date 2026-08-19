import pypdf

pdf_path = r"C:\Users\32755\Desktop\机器人后台\华数二次开发\二次开发资料\hsc3api_vc++_msvc140\通讯功能命令说明文档_A0_CN.pdf"

reader = pypdf.PdfReader(pdf_path)
print(f"Total pages in PDF: {len(reader.pages)}")
with open(r"D:\Antigravity projects\机器人管理系统\huashu_protocol_pdf.txt", "w", encoding="utf-8") as out:
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        out.write(f"\n--- PAGE {i+1} ---\n")
        out.write(text)
print("SUCCESS: Exported PDF text to huashu_protocol_pdf.txt")
