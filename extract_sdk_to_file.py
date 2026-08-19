import os

base_dir = r"C:\Users\32755\Desktop\机器人后台\华数二次开发\二次开发资料"

out_file = r"D:\Antigravity projects\机器人管理系统\huashu_sdk_extracted.txt"
with open(out_file, 'w', encoding='utf-8') as out:
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.endswith(('.cs', '.cpp', '.h')) and not 'packages' in root:
                fpath = os.path.join(root, f)
                out.write("\n" + "="*70 + "\n")
                out.write(f"FILE: {fpath}\n")
                out.write("="*70 + "\n")
                try:
                    content = open(fpath, 'r', encoding='utf-8', errors='ignore').read()
                    out.write(content)
                except Exception as e:
                    out.write(f"Error: {e}\n")

print(f"Extracted all SDK code to {out_file}")
