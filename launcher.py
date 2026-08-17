import os
import sys

# Override env vars so main.py and mock_robot.py skip MQTT auth
os.environ["MQTT_USERNAME"] = ""
os.environ["MQTT_PASSWORD"] = ""

if len(sys.argv) > 1 and sys.argv[1] == "mock":
    sys.argv = ["mock_robot.py", "--num-devices", "10"]
    import mock_robot
    mock_robot.main()
else:
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
