import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

# Check running process
stdin, stdout, stderr = client.exec_command("ps aux | grep main.py")
print("PROCESS:")
print(stdout.read().decode('utf-8'))

# Find all .db files
stdin, stdout, stderr = client.exec_command("find /home/qtz -name '*.db'")
print("DB FILES:")
print(stdout.read().decode('utf-8'))

# Check devices table in all found db files
stdin, stdout, stderr = client.exec_command("""
python3 -c "
import glob, sqlite3
for db in glob.glob('/home/qtz/**/*.db', recursive=True):
    print('=== DB:', db)
    try:
        conn = sqlite3.connect(db)
        c = conn.cursor()
        for row in c.execute('SELECT id, device_id, model FROM devices').fetchall():
            print(row)
        conn.close()
    except Exception as e:
        print('Error:', e)
"
""")
print("DB CONTENTS:")
print(stdout.read().decode('utf-8'))
print("ERR:", stderr.read().decode('utf-8'))

client.close()
