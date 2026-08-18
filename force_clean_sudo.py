import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

# Python script to run with sudo
script = """
import sqlite3, glob, os

db_path = '/home/qtz/桌面/robot-iot-standalone/app/robot.db'
print("Connecting to:", db_path)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# 1. Look at all devices currently
rows = c.execute("SELECT id, device_id, device_type, status FROM devices").fetchall()
print("Before delete, devices count:", len(rows))
for r in rows:
    print("  ", r)

# 2. Delete all 诗歌 devices and offline test devices, only keep the 10 active 远程测试机器人
c.execute("DELETE FROM devices WHERE status = 'offline' OR id < 550914")
c.execute("DELETE FROM device_data WHERE device_id NOT IN (SELECT device_id FROM devices)")

conn.commit()

rows_after = c.execute("SELECT id, device_id, device_type, status FROM devices").fetchall()
print("After delete, devices count:", len(rows_after))
for r in rows_after:
    print("  ", r)

conn.close()
"""

sftp = client.open_sftp()
with sftp.open('/home/qtz/force_clean.py', 'w') as f:
    f.write(script)
sftp.close()

# Run with sudo
stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S python3 /home/qtz/force_clean.py")
print("EXEC RESULT:")
print(stdout.read().decode('utf-8'))
print(stderr.read().decode('utf-8'))

client.close()
