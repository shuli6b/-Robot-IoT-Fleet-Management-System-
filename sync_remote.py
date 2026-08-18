import paramiko
import os

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

sftp = client.open_sftp()

files_to_sync = [
    (r"D:\Antigravity projects\机器人管理系统\database.py", "database.py"),
    (r"D:\Antigravity projects\机器人管理系统\main.py", "main.py"),
    (r"D:\Antigravity projects\机器人管理系统\static\index.html", "static/index.html"),
]

target_dirs = [
    "/home/qtz/桌面/robot-iot-standalone/app",
    "/home/qtz/robot-iot-standalone",
]

for src_local, rel_path in files_to_sync:
    print(f"Uploading {rel_path}...")
    for t_dir in target_dirs:
        dest_remote = f"{t_dir}/{rel_path}"
        try:
            # Ensure parent dir exists
            p_dir = os.path.dirname(dest_remote)
            stdin, stdout, stderr = client.exec_command(f"mkdir -p '{p_dir}'")
            stdout.read()
            sftp.put(src_local, dest_remote)
            print(f"  -> Uploaded to {dest_remote}")
        except Exception as e:
            print(f"  -> Failed to upload to {dest_remote}: {e}")

sftp.close()

# Restart robot-iot service
print("Restarting service...")
stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S systemctl restart robot-iot")
print(stdout.read().decode('utf-8'))
print(stderr.read().decode('utf-8'))

client.close()
print("Hot reload complete!")
