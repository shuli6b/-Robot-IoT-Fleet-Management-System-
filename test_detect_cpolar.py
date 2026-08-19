import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

script = """
import os, subprocess, re

def detect_cpolar_tunnels():
    tunnels = {}
    
    # 1. Try reading cpolar.yml
    for path in ['/usr/local/etc/cpolar/cpolar.yml', os.path.expanduser('~/.cpolar/cpolar.yml')]:
        if os.path.exists(path):
            tunnels['config_file'] = path
            
    # 2. Try journalctl logs
    try:
        p = subprocess.Popen(['sudo', 'journalctl', '-u', 'cpolar', '-n', '200', '--no-pager'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate()
        lines = out.decode('utf-8', errors='ignore').split('\\n')
        for l in lines:
            # find tcp:// or http:// or https://
            matches = re.findall(r'(https?://[a-zA-Z0-9_\\-\\.]+\\.cpolar\\.[a-zA-Z0-9]+)', l)
            for m in matches:
                tunnels['web_url'] = m
            tcp_matches = re.findall(r'(tcp://[a-zA-Z0-9_\\-\\.]+\\.cpolar\\.[a-zA-Z0-9]+:\\d+)', l)
            for m in tcp_matches:
                if '22' in l or 'ssh' in l:
                    tunnels['ssh_url'] = m
                elif '1883' in l or 'mqtt' in l:
                    tunnels['mqtt_url'] = m
    except Exception as e:
        tunnels['err'] = str(e)
        
    print("Detected tunnels:", tunnels)

detect_cpolar_tunnels()
"""

sftp = client.open_sftp()
with sftp.open('/home/qtz/test_detect.py', 'w') as f:
    f.write(script)
sftp.close()

stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S python3 /home/qtz/test_detect.py")
print(stdout.read().decode('utf-8'))
print(stderr.read().decode('utf-8'))

client.close()
