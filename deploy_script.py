import paramiko
import time

hostname = "20.tcp.cpolar.top"
port = 11653
username = "qtz"
password = "qtz666"

print(f"Connecting to {username}@{hostname}:{port}...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect(hostname, port=port, username=username, password=password, timeout=10)
    print("Connected successfully!")
    
    commands = [
        "sudo apt update -y",
        "sudo apt install -y python3-venv python3-pip git mosquitto",
        "sudo systemctl enable mosquitto",
        "sudo systemctl start mosquitto",
        "git clone https://github.com/shuli6b/-Robot-IoT-Fleet-Management-System-.git || (cd -Robot-IoT-Fleet-Management-System- && git pull)",
        "cd -Robot-IoT-Fleet-Management-System- && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt",
        
        # Add mqtt tunnel to cpolar
        "echo '\\n  iot-mqtt:\\n    addr: 1883\\n    proto: tcp\\n    region: cn' | sudo tee -a /usr/local/etc/cpolar/cpolar.yml",
        "sudo systemctl restart cpolar",
        
        # Install robot-iot service
        "cd -Robot-IoT-Fleet-Management-System- && sudo cp robot-iot.service /etc/systemd/system/",
        # Update working directory in service file
        "sudo sed -i 's|WorkingDirectory=/home/ubuntu/-Robot-IoT-Fleet-Management-System-|WorkingDirectory=/home/qtz/-Robot-IoT-Fleet-Management-System-|g' /etc/systemd/system/robot-iot.service",
        "sudo sed -i 's|User=ubuntu|User=qtz|g' /etc/systemd/system/robot-iot.service",
        "sudo sed -i 's|ExecStart=/home/ubuntu/-Robot-IoT-Fleet-Management-System-/venv/bin/python main.py|ExecStart=/home/qtz/-Robot-IoT-Fleet-Management-System-/venv/bin/python main.py|g' /etc/systemd/system/robot-iot.service",
        
        "sudo systemctl daemon-reload",
        "sudo systemctl enable robot-iot",
        "sudo systemctl restart robot-iot"
    ]
    
    for cmd in commands:
        print(f"Executing: {cmd}")
        # Execute with sudo requires passing password
        stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S bash -c \"{cmd}\"")
        out = stdout.read().decode('utf-8')
        err = stderr.read().decode('utf-8')
        if out: print(out)
        if err: print(err)
        
    print("Deployment sequence finished!")
except Exception as e:
    print(f"Failed: {e}")
finally:
    client.close()
