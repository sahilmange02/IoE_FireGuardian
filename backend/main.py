import json
import os
import serial
import threading
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# -------------------------------
# Configuration
# -------------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SERIAL_PORT = "COM3"
BAUD_RATE = 9600
simulated_folder = "simulated_data"
live_data_folder = "live_data"
os.makedirs(live_data_folder, exist_ok=True)

# Global storage for live readings
helmet_live_data = {"helmet_id": "H1", "history": []}


# -------------------------------
# Load simulated helmets (H2–H4)
# -------------------------------
def load_simulated_data():
    helmets = []
    for fname in os.listdir(simulated_folder):
        if fname.endswith(".json"):
            path = os.path.join(simulated_folder, fname)
            with open(path, "r") as f:
                data = json.load(f)
                helmets.append(data)
    return helmets


# -------------------------------
# Read Arduino data (live H1)
# -------------------------------
def read_from_arduino():
    global helmet_live_data
    try:
        arduino = serial.Serial(SERIAL_PORT, BAUD_RATE)
        print(f"✅ Connected to Arduino on {SERIAL_PORT}")
        time.sleep(2)
    except Exception as e:
        print(f"⚠️ Could not connect to Arduino: {e}")
        return

    while True:
        try:
            line = arduino.readline().decode("utf-8", errors="ignore").strip()
            if "Temperature" in line:
                temp = float(line.split(":")[1])
            elif "MQ2 Value" in line:
                mq2_value = int(line.split(":")[1])
            elif "Flame Detected?" in line:
                flame_detected = "YES" in line
            elif "ALERT STATUS" in line:
                alert = "ALERT" in line or "🚨" in line

                # Build a reading entry
                reading = {
                    "timestamp": time.strftime("%H:%M:%S"),
                    "temperature": temp,
                    "mq2_value": mq2_value,
                    "flame_detected": flame_detected,
                    "alert_status": "ALERT" if alert else "Normal",
                }

                helmet_live_data["helmet_id"] = "H1"
                helmet_live_data["history"].append(reading)

                # Save to local JSON
                with open(os.path.join(live_data_folder, "h1_history.json"), "w") as f:
                    json.dump(helmet_live_data, f, indent=4)

                print(f"📡 Live update added: {reading}")

        except Exception as e:
            print(f"⚠️ Error reading from Arduino: {e}")
            time.sleep(2)


# Start background thread for Arduino data
threading.Thread(target=read_from_arduino, daemon=True).start()


# -------------------------------
# API: Get all helmets data
# -------------------------------
@app.get("/helmets")
def get_all_helmets():
    helmets = []

    # Load simulated helmets
    helmets += load_simulated_data()

    # Add live helmet (H1)
    try:
        with open(os.path.join(live_data_folder, "h1_history.json"), "r") as f:
            h1_data = json.load(f)
        helmets.insert(0, h1_data)
    except FileNotFoundError:
        helmets.insert(0, {"helmet_id": "H1", "status": "No recent data"})

    return {"helmets": helmets}
