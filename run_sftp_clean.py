import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

sftp = client.open_sftp()

script_content = """import os, sqlite3, glob

print("Scanning for sqlite databases...")
for root, dirs, files in os.walk('/home/qtz'):
    for f in files:
        if f.endswith('.db'):
            db_path = os.path.join(root, f)
            try:
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if 'devices' in tables:
                    print("Found IoT DB at:", db_path)
                    print("Tables:", tables)
                    cols = [col[1] for col in c.execute("PRAGMA table_info(devices)").fetchall()]
                    print("Cols in devices:", cols)
                    rows = c.execute("SELECT * FROM devices").fetchall()
                    print(f"Total devices ({len(rows)}):")
                    for r in rows:
                        print(" ", r)
                    
                    # Delete all devices that don't match our 10 remote test robots
                    c.execute("DELETE FROM devices WHERE device_id LIKE '%诗歌%' OR device_id LIKE '%shige%'")
                    c.execute("DELETE FROM device_data WHERE device_id LIKE '%诗歌%' OR device_id LIKE '%shige%'")
                    conn.commit()
                    print("Cleaned up 诗歌 records!")
                conn.close()
            except Exception as e:
                pass
"""

with sftp.open('/home/qtz/clean_script.py', 'w') as f:
    f.write(script_content)
sftp.close()

print("Executing clean_script.py...")
stdin, stdout, stderr = client.exec_command("python3 /home/qtz/clean_script.py")
print("STDOUT:")
print(stdout.read().decode('utf-8'))
print("STDERR:")
print(stderr.read().decode('utf-8'))

# Restart service
print("Restarting robot-iot service...")
stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S systemctl restart robot-iot")
print(stdout.read().decode('utf-8'))
print(stderr.read().decode('utf-8'))

client.close()
