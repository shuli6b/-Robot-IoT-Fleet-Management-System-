import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

python_script = """
import sqlite3
import os

db_path = "/home/qtz/robot-iot-standalone/robot.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("DELETE FROM devices WHERE device_id LIKE '%诗歌%' OR model LIKE '%诗歌%'")
    c.execute("DELETE FROM device_data WHERE device_id LIKE '%诗歌%'")
    c.execute("DELETE FROM devices WHERE device_id NOT LIKE 'arm_%' AND device_id NOT LIKE 'amr_%' AND device_id NOT LIKE 'dog_%' AND device_id NOT LIKE '远程测试机器人_%'")
    conn.commit()
    conn.close()
"""

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

# Run inline python via python3 -c
cmd = "python3 -c \"{}\"".format(python_script.replace('\n', ' '))
# wait, replacing newlines with spaces will break python indentation!
# better to pass via stdin to python3
stdin, stdout, stderr = client.exec_command("cd /home/qtz/robot-iot-standalone && ./venv/bin/python3 -")
stdin.write(python_script)
stdin.close()

print("OUT:", stdout.read().decode('utf-8'))
print("ERR:", stderr.read().decode('utf-8'))

client.close()
