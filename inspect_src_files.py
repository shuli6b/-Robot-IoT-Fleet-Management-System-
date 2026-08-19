import os

base_dir = r"C:\Users\32755\Desktop\机器人后台\华数二次开发\二次开发资料"

for root, dirs, files in os.walk(base_dir):
    for f in files:
        if f.endswith(('.cs', '.cpp', '.h')) and not 'packages' in root:
            fpath = os.path.join(root, f)
            print("==================================================")
            print("FILE:", fpath)
            try:
                content = open(fpath, 'r', encoding='utf-8', errors='ignore').read()
                print(content[:2500])
            except Exception as e:
                print("Error reading:", e)
