import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

check_script = """import sqlite3
conn = sqlite3.connect('/home/qtz/桌面/robot-iot-standalone/app/robot.db')
c = conn.cursor()
rows = c.execute("SELECT id, device_id, device_type, status FROM devices").fetchall()
print(f"Total current devices in DB: {len(rows)}")
for r in rows:
    print(r)
conn.close()
"""

sftp = client.open_sftp()
with sftp.open('/home/qtz/check_now.py', 'w') as f:
    f.write(check_script)
sftp.close()

stdin, stdout, stderr = client.exec_command("python3 /home/qtz/check_now.py")
print("RESULT:")
print(stdout.read().decode('utf-8'))

client.close()
