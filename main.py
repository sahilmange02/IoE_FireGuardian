import json
import os
import re
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

SERIAL_PORT = "COM7."
BAUD_RATE = 9600
simulated_folder = "simulated_data"
live_data_folder = "live_data"
os.makedirs(live_data_folder, exist_ok=True)

# Global storage for live H1 readings
# Includes both current flat format (for card display) and history (for charts)
helmet_live_data = {
    "helmet_id": "H1",
    "name": "John Doe",
    "temperature": 0,
    "humidity": 0,
    "mq2_value": 0,
    "flame_detected": False,
    "alert_status": "Normal",
    "heartRate": 0,
    "spo2": 0,
    "history": []  # Time-series history for charts
}

# Temporary storage for current reading being assembled
current_reading = {
    "temperature": None,
    "mq2_value": None,
    "flame_detected": None,
    "heart_rate": None,
    "heart_rate_avg": None,
    "spo2": None,
    "alert_status": None
}


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
    global helmet_live_data, current_reading
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

            # Skip empty lines
            if not line:
                continue

            # normalize some unicode names (e.g. SpO₂)
            norm = line.replace("SpO₂", "SpO2").replace("º", "").strip()

            # helper to extract FIRST number AFTER colon (or first number if no colon)
            def extract_number(s: str):
                # If there's a colon, extract from after it
                if ":" in s:
                    s = s.split(":", 1)[1]  # Take everything after first colon
                m = re.search(r"[-+]?\d*\.?\d+", s)
                if not m:
                    return None
                try:
                    return float(m.group())
                except ValueError:
                    return None

            # Parse Temperature (explicit: look for "Temperature" keyword)
            if "Temperature" in norm and ":" in norm:
                temp_val = extract_number(norm)
                current_reading["temperature"] = float(temp_val) if temp_val is not None else 0.0
                print(f"  [TEMP] Extracted: {current_reading['temperature']}")

            # Parse MQ2 Value (explicit: look for "MQ2 Value" keyword)
            elif "MQ2 Value" in norm:
                mq2_val = extract_number(norm)
                current_reading["mq2_value"] = int(mq2_val) if mq2_val is not None else 0
                print(f"  [MQ2] Extracted: {current_reading['mq2_value']}")

            # Parse Smoke Detected (explicit keyword check)
            elif "Smoke Detected" in norm:
                current_reading["flame_detected"] = False  # Reset flame when we see smoke line
                if "YES" in norm.upper():
                    current_reading["alert_status"] = "Smoke Alert"
                print(f"  [SMOKE] Detected: {current_reading['alert_status']}")

            # Parse Flame Detected (explicit keyword check - after MQ2 to avoid conflicts)
            elif "Flame Detected?" in norm or ("Flame Detected" in norm and "Flame Raw" not in norm):
                current_reading["flame_detected"] = "YES" in norm.upper()
                print(f"  [FLAME] Detected: {current_reading['flame_detected']}")

            # Parse Avg HR specifically (must come before instant HR)
            elif "Avg HR" in norm:
                hr_avg_val = extract_number(norm)
                current_reading["heart_rate_avg"] = float(hr_avg_val) if hr_avg_val is not None else None
                print(f"  [AVG HR] Extracted: {current_reading['heart_rate_avg']}")

            # Parse Heart Rate (instant) - explicit "HR (BPM)" or "Heart Rate"
            elif "HR (BPM)" in norm or "Heart Rate" in norm:
                hr_val = extract_number(norm)
                current_reading["heart_rate"] = float(hr_val) if hr_val is not None else None
                print(f"  [HR] Extracted: {current_reading['heart_rate']}")

            # Parse SpO2 - MUST have "SpO2 (%)" pattern, not just any "SpO2" (to avoid matching "HR/SpO2 Alert")
            elif "SpO2 (%)" in norm:
                spo2_val = extract_number(norm)
                current_reading["spo2"] = float(spo2_val) if spo2_val is not None else 0.0
                print(f"  [SPO2] Extracted: {current_reading['spo2']}")
            
            # Alert Status triggers the save of complete reading
            elif "ALERT STATUS" in line:
                alert = "ALERT" in line or "🚨" in line
                current_reading["alert_status"] = "ALERT" if alert else "Normal"
                print(f"  [ALERT] Status: {current_reading['alert_status']}")

                # Only update if we have at least some core data
                if current_reading["temperature"] is not None or current_reading["mq2_value"] is not None:
                    # Update the flat current fields (for card display)
                    helmet_live_data["temperature"] = current_reading["temperature"]
                    helmet_live_data["mq2_value"] = current_reading["mq2_value"]
                    helmet_live_data["flame_detected"] = current_reading["flame_detected"]
                    # Prefer instant heart rate; fall back to avg if instant is missing
                    helmet_live_data["heartRate"] = current_reading["heart_rate"] if current_reading.get("heart_rate") is not None else current_reading.get("heart_rate_avg")
                    helmet_live_data["spo2"] = current_reading["spo2"]
                    helmet_live_data["alert_status"] = current_reading["alert_status"]

                    # Create a history entry with timestamp (include both instant and avg HR if present)
                    history_entry = {
                        "timestamp": time.strftime("%H:%M:%S"),
                        "temperature": current_reading["temperature"],
                        "mq2_value": current_reading["mq2_value"],
                        "flame_detected": current_reading["flame_detected"],
                        "heart_rate": current_reading["heart_rate"],
                        "heart_rate_avg": current_reading.get("heart_rate_avg"),
                        "spo2": current_reading["spo2"],
                        "alert_status": current_reading["alert_status"]
                    }

                    # Append to history (keep last 100 readings)
                    helmet_live_data["history"].append(history_entry)
                    if len(helmet_live_data["history"]) > 100:
                        helmet_live_data["history"].pop(0)

                    # Save to local JSON
                    with open(os.path.join(live_data_folder, "h1_history.json"), "w") as f:
                        json.dump(helmet_live_data, f, indent=4)

                    print(f"📡 Live reading saved:")
                    print(f"   Temp: {helmet_live_data['temperature']} | MQ2: {helmet_live_data['mq2_value']} | HR: {helmet_live_data['heartRate']} | SpO2: {helmet_live_data['spo2']}")

                    # Reset for next reading
                    current_reading = {
                        "temperature": None,
                        "mq2_value": None,
                        "flame_detected": None,
                        "heart_rate": None,
                        "heart_rate_avg": None,
                        "spo2": None,
                        "alert_status": None
                    }

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
