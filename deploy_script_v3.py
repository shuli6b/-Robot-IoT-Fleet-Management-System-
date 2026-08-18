import paramiko
import time
import os

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

zip_path = r"D:\Antigravity projects\机器人管理系统\offline_deploy\robot-iot-standalone.zip"

print(f"Connecting to {username}@{hostname}:{port}...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect(hostname, port=port, username=username, password=password, timeout=10)
    print("Connected successfully!")
    
    print("Uploading zip file...")
    sftp = client.open_sftp()
    sftp.put(zip_path, "/home/qtz/robot-iot-standalone.zip")
    sftp.close()
    print("Upload complete.")
    
    commands = [
        "sudo apt update -y && sudo apt install -y unzip python3-venv python3-pip mosquitto",
        "sudo systemctl enable mosquitto",
        "sudo systemctl start mosquitto",
        "rm -rf ./robot-iot-standalone && unzip -q /home/qtz/robot-iot-standalone.zip -d ./robot-iot-standalone",
        "cd ./robot-iot-standalone && python3 -m venv venv && ./venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt",
        
        # Install robot-iot service
        "cd ./robot-iot-standalone && sudo cp robot-iot.service /etc/systemd/system/",
        "sudo sed -i 's|WorkingDirectory=/home/ubuntu/-Robot-IoT-Fleet-Management-System-|WorkingDirectory=/home/qtz/robot-iot-standalone|g' /etc/systemd/system/robot-iot.service",
        "sudo sed -i 's|User=ubuntu|User=qtz|g' /etc/systemd/system/robot-iot.service",
        "sudo sed -i 's|ExecStart=/home/ubuntu/-Robot-IoT-Fleet-Management-System-/venv/bin/python main.py|ExecStart=/home/qtz/robot-iot-standalone/venv/bin/python main.py|g' /etc/systemd/system/robot-iot.service",
        
        "sudo systemctl daemon-reload",
        "sudo systemctl enable robot-iot",
        "sudo systemctl restart robot-iot"
    ]
    
    for cmd in commands:
        print(f"Executing: {cmd}")
        stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S bash -c \"{cmd}\"")
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        if out: print("OUT:", out.strip())
        if err: print("ERR:", err.strip())
        
    print("Deployment sequence finished!")
except Exception as e:
    print(f"Failed: {e}")
finally:
    client.close()
