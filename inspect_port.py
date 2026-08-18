import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

# Check what is listening on port 8000
stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S ss -tlpn | grep 8000")
print("PORT 8000:")
print(stdout.read().decode('utf-8'))

# Check systemctl status robot-iot
stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S systemctl status robot-iot")
print("SYSTEMCTL STATUS:")
print(stdout.read().decode('utf-8'))

# Check process with port 8000 PID
stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S lsof -i :8000")
print("LSOF 8000:")
print(stdout.read().decode('utf-8'))

# Inspect all tables in /home/qtz/桌面/robot-iot-standalone/app/robot.db and others
stdin, stdout, stderr = client.exec_command("""
python3 -c "
import glob, sqlite3
for db in glob.glob('/home/qtz/**/*.db', recursive=True):
    if 'xwechat' in db or '.local' in db or '.pki' in db or 'snap' in db or '.cache' in db: continue
    print('=== DB:', db)
    try:
        conn = sqlite3.connect(db)
        c = conn.cursor()
        for t in c.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall():
            tname = t[0]
            print('  Table:', tname)
            cols = [col[1] for col in c.execute(f'PRAGMA table_info({tname})').fetchall()]
            print('    Cols:', cols)
            rows = c.execute(f'SELECT * FROM {tname}').fetchall()
            print(f'    Rows ({len(rows)}):', rows[:5])
        conn.close()
    except Exception as e:
        print('  Error:', e)
"
""")
print("DB TABLES:")
print(stdout.read().decode('utf-8'))

client.close()
