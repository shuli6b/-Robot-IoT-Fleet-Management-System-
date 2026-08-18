import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

# Check cwd of pid 212375
stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S ls -la /proc/212375/cwd /proc/212375/fd")
print("PROC CWD & FDS:")
print(stdout.read().decode('utf-8'))

# Delete all databases across all locations that contain 诗歌
clean_script = """
import os, glob, sqlite3

for root, dirs, files in os.walk('/home/qtz'):
    for f in files:
        if f.endswith('.db') and ('xwechat' not in root and '.local' not in root and '.pki' not in root and 'snap' not in root and '.cache' not in root):
            db_path = os.path.join(root, f)
            print("Checking DB:", db_path)
            try:
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                # Check tables
                tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                print("  Tables:", tables)
                if 'devices' in tables:
                    devs = c.execute("SELECT id, device_id, custom_name, model_type FROM devices").fetchall()
                    print("  Current devices in DB:", devs)
                    c.execute("DELETE FROM devices WHERE device_id LIKE '%诗歌%' OR custom_name LIKE '%诗歌%' OR device_id LIKE '%shige%'")
                    c.execute("DELETE FROM device_data WHERE device_id LIKE '%诗歌%' OR device_id LIKE '%shige%'")
                    conn.commit()
                    print("  Cleaned up 诗歌!")
                conn.close()
            except Exception as e:
                print("  Error:", e)
"""

stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S python3 -c \"" + clean_script.replace('\n', '\n') + "\"")
# Pass via stdin
stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S python3 -")
stdin.write(clean_script)
stdin.close()
print("CLEAN RESULT:")
print(stdout.read().decode('utf-8'))
print("ERR:", stderr.read().decode('utf-8'))

# Restart the service to refresh in-memory caches
stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S systemctl restart robot-iot")
print("RESTART RESULT:", stdout.read().decode('utf-8'))

client.close()
