import machine
import onewire
import ds18x20
import time
import network
import ntptime
import os
import socket
import json

# --- Wi-Fi & Time Setup ---
WIFI_SSID = "<WIFI-SSID>"
WIFI_PASSWORD = "<WIFI-PASSWORD>"
IST_OFFSET = 19800 

print("Connecting to Wi-Fi...")
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID, WIFI_PASSWORD)

max_wait = 15
while max_wait > 0:
    if wlan.status() < 0 or wlan.status() >= 3:
        break
    max_wait -= 1
    time.sleep(1)

if wlan.status() == 3:
    print("Wi-Fi connected! IP:", wlan.ifconfig()[0])
    try:
        ntptime.settime() 
        ist_epoch = time.time() + IST_OFFSET
        tm = time.localtime(ist_epoch)
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
    except Exception:
        pass
else:
    print("Wi-Fi failed.")

# --- Setup Sensors & Controls ---
ds_pin = machine.Pin(16)
ds_sensor = ds18x20.DS18X20(onewire.OneWire(ds_pin))
voltage_adc = machine.ADC(26)
current_adc = machine.ADC(27)

peltier_pwm = machine.PWM(machine.Pin(14)) 
peltier_pwm.freq(1000)
peltier_pwm.duty_u16(0)

in1 = machine.Pin(13, machine.Pin.OUT)
in2 = machine.Pin(12, machine.Pin.OUT)

# --- Constants & Calibration ---
ADC_TO_VOLTS = 3.3 / 65535
VOLTAGE_DIVIDER_RATIO = 5.0 
ACS712_OFFSET = 2.522 
ACS712_SENSITIVITY = 0.100 

# Sensor Addresses (UPDATE THESE)
ROOM_ADDR = bytearray(b'(\xf9\xa6u\xd0\x01<\xbc')
COOLER_ADDR = bytearray(b'(\x8f\xfcu\xd0\x01<\xbe') 
EXHAUST_ADDR = bytearray(b'(\xd8\x7fu\xd0\x01<\x90') 

FILE_NAME = "data_log.csv"
BACKUP_FILE_NAME = "data_log_backup.csv"
SETTINGS_FILE = "settings.json"
HEADER = "time,voltage,current,roomtemp,coolertemp,exhusttemp,power_percent,status,mode\n"
MAX_FILE_SIZE = 512000 

# ==========================================
# --- SMART AC SETTINGS MANAGEMENT ---
# ==========================================
DEFAULT_SETTINGS = {
    "MODE": "COOL",
    "COOL_TARGET": 20.0,
    "COOL_MAX": 23.0,
    "EXHAUST_DANGER": 45.0,
    "HEAT_TARGET": 38.0,
    "HEAT_MIN": 33.0,
    "NECK_DANGER": 45.0
}

def load_settings():
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        # File doesn't exist or is corrupted, load defaults and create file
        print("Loading default settings...")
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()

def save_settings(settings_dict):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings_dict, f)
        print("Settings saved to flash.")
    except Exception as e:
        print("Failed to save settings:", e)

# Load settings at boot
settings = load_settings()

MODE = settings.get("MODE", "COOL")
COOL_TARGET = settings.get("COOL_TARGET", 20.0)
COOL_MAX = settings.get("COOL_MAX", 23.0)
EXHAUST_DANGER = settings.get("EXHAUST_DANGER", 45.0)
HEAT_TARGET = settings.get("HEAT_TARGET", 38.0)
HEAT_MIN = settings.get("HEAT_MIN", 33.0)
NECK_DANGER = settings.get("NECK_DANGER", 45.0)

# Data storage for Web Server
recent_data = [] 
current_state = {}

try:
    with open(FILE_NAME, "r") as file:
        pass
except OSError:
    with open(FILE_NAME, "w") as file:
        file.write(HEADER)

# --- Web Server Setup ---
s = socket.socket()
s.bind(('', 80))
s.listen(5)
s.setblocking(False)

# HTML Template
HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
    <title>Smart AC Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial; margin: 20px; background: #f4f4f9; }
        .card { background: white; padding: 20px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h2 { margin-top: 0; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
        input, select, button { padding: 8px; margin: 5px 0; width: 100%; box-sizing: border-box; }
        button { background: #007bff; color: white; border: none; cursor: pointer; border-radius: 4px; font-weight: bold; }
        button:hover { background: #0056b3; }
        .download-btn { background: #28a745; margin-top: 10px; }
        .download-btn:hover { background: #218838; }
    </style>
</head>
<body>
    <h1>Smart AC Controller</h1>
    
    <div class="card grid" id="live-data">
        <div><strong>Status:</strong> <span id="val_status">Loading...</span></div>
        <div><strong>Mode:</strong> <span id="val_mode">Loading...</span></div>
        <div><strong>Room Temp:</strong> <span id="val_room">--</span> &deg;C</div>
        <div><strong>Cooler Temp:</strong> <span id="val_cooler">--</span> &deg;C</div>
        <div><strong>Exhaust Temp:</strong> <span id="val_exhaust">--</span> &deg;C</div>
        <div><strong>Voltage:</strong> <span id="val_v">--</span> V</div>
        <div><strong>Current:</strong> <span id="val_i">--</span> A</div>
        <div><strong>Power Level:</strong> <span id="val_p">--</span>%</div>
    </div>

    <div class="card">
        <h2>Settings Configuration</h2>
        <form action="/update" method="GET">
            <div class="grid">
                <div><label>Mode:</label><select name="mode"><option value="COOL">COOL</option><option value="HEAT">HEAT</option></select></div>
                <div><label>Cool Target (&deg;C):</label><input type="number" step="0.1" name="ct" id="set_ct"></div>
                <div><label>Cool Max (&deg;C):</label><input type="number" step="0.1" name="cm" id="set_cm"></div>
                <div><label>Exhaust Danger (&deg;C):</label><input type="number" step="0.1" name="ed" id="set_ed"></div>
                <div><label>Heat Target (&deg;C):</label><input type="number" step="0.1" name="ht" id="set_ht"></div>
                <div><label>Heat Min (&deg;C):</label><input type="number" step="0.1" name="hm" id="set_hm"></div>
                <div><label>Neck Danger (&deg;C):</label><input type="number" step="0.1" name="nd" id="set_nd"></div>
            </div>
            <button type="submit">Save & Apply Settings</button>
        </form>
        <button class="download-btn" onclick="window.location.href='/download'">Download Full Logs (CSV)</button>
    </div>

    <div class="card">
        <h2>Last 20 Readings</h2>
        <table>
            <thead><tr><th>Time</th><th>Room</th><th>Cooler</th><th>Exhaust</th><th>Volt</th><th>Curr</th><th>Pwr</th></tr></thead>
            <tbody id="history-table"></tbody>
        </table>
    </div>

    <script>
        function fetchData() {
            fetch('/data').then(r => r.json()).then(data => {
                const cur = data.current;
                document.getElementById('val_status').innerText = cur.status;
                document.getElementById('val_mode').innerText = cur.mode;
                document.getElementById('val_room').innerText = cur.room;
                document.getElementById('val_cooler').innerText = cur.cooler;
                document.getElementById('val_exhaust').innerText = cur.exhaust;
                document.getElementById('val_v').innerText = cur.v;
                document.getElementById('val_i').innerText = cur.i;
                document.getElementById('val_p').innerText = cur.p;
                
                // Update forms if not focused
                if(!document.activeElement.tagName.match(/INPUT|SELECT/)){
                    document.querySelector(`select[name="mode"]`).value = data.settings.mode;
                    document.getElementById('set_ct').value = data.settings.ct;
                    document.getElementById('set_cm').value = data.settings.cm;
                    document.getElementById('set_ed').value = data.settings.ed;
                    document.getElementById('set_ht').value = data.settings.ht;
                    document.getElementById('set_hm').value = data.settings.hm;
                    document.getElementById('set_nd').value = data.settings.nd;
                }

                let tbody = '';
                data.history.forEach(row => {
                    tbody += `<tr><td>${row.time}</td><td>${row.room}</td><td>${row.cooler}</td><td>${row.exhaust}</td><td>${row.v}</td><td>${row.i}</td><td>${row.p}%</td></tr>`;
                });
                document.getElementById('history-table').innerHTML = tbody;
            });
        }
        setInterval(fetchData, 2000);
        fetchData();
    </script>
</body>
</html>
"""

def parse_url_args(request_line):
    args = {}
    try:
        url = request_line.split(' ')[1]
        if '?' in url:
            query = url.split('?')[1]
            for param in query.split('&'):
                key, val = param.split('=')
                args[key] = val
    except Exception:
        pass
    return args

def handle_web_requests():
    global MODE, COOL_TARGET, COOL_MAX, EXHAUST_DANGER, HEAT_TARGET, HEAT_MIN, NECK_DANGER
    try:
        conn, addr = s.accept()
        conn.settimeout(2.0)
        request = conn.recv(1024).decode('utf-8')
        
        if not request:
            conn.close()
            return

        # Serve Main Page
        if "GET / " in request or "GET /index" in request:
            conn.send('HTTP/1.1 200 OK\nContent-Type: text/html\nConnection: close\n\n')
            conn.send(HTML_PAGE)
        
        # Serve JSON Data (Live refresh)
        elif "GET /data " in request:
            payload = {
                "current": current_state,
                "settings": {
                    "mode": MODE, "ct": COOL_TARGET, "cm": COOL_MAX, "ed": EXHAUST_DANGER,
                    "ht": HEAT_TARGET, "hm": HEAT_MIN, "nd": NECK_DANGER
                },
                "history": recent_data
            }
            conn.send('HTTP/1.1 200 OK\nContent-Type: application/json\nConnection: close\n\n')
            conn.send(json.dumps(payload))
            
        # Update Settings
        elif "GET /update?" in request:
            args = parse_url_args(request)
            updated = False
            
            if 'mode' in args: MODE = args['mode']; updated = True
            if 'ct' in args: COOL_TARGET = float(args['ct']); updated = True
            if 'cm' in args: COOL_MAX = float(args['cm']); updated = True
            if 'ed' in args: EXHAUST_DANGER = float(args['ed']); updated = True
            if 'ht' in args: HEAT_TARGET = float(args['ht']); updated = True
            if 'hm' in args: HEAT_MIN = float(args['hm']); updated = True
            if 'nd' in args: NECK_DANGER = float(args['nd']); updated = True
            
            # Save the new global variables to flash memory
            if updated:
                new_config = {
                    "MODE": MODE, "COOL_TARGET": COOL_TARGET, "COOL_MAX": COOL_MAX,
                    "EXHAUST_DANGER": EXHAUST_DANGER, "HEAT_TARGET": HEAT_TARGET,
                    "HEAT_MIN": HEAT_MIN, "NECK_DANGER": NECK_DANGER
                }
                save_settings(new_config)
            
            # Redirect back to home
            conn.send('HTTP/1.1 303 See Other\nLocation: /\nConnection: close\n\n')
            
        # Download Logs
        elif "GET /download " in request:
            conn.send('HTTP/1.1 200 OK\nContent-Type: text/csv\nContent-Disposition: attachment; filename="data_log.csv"\nConnection: close\n\n')
            try:
                with open(FILE_NAME, 'r') as f:
                    while True:
                        chunk = f.read(512)
                        if not chunk: break
                        conn.send(chunk)
            except OSError:
                conn.send("Log file error.")
        else:
            conn.send('HTTP/1.1 404 Not Found\nConnection: close\n\n')
            
        conn.close()
    except OSError:
        pass 

def wait_and_serve(duration_ms):
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < duration_ms:
        handle_web_requests()
        time.sleep_ms(20) 


# Initialize the Integral Boost memory variable
integral_boost = 0.0
print("System running. Access Web UI at IP above.")

while True:
    ds_sensor.convert_temp()
    
    # Wait for sensor conversion (750ms required) while serving web pages
    wait_and_serve(750) 
        
    t = time.localtime()
    timestamp = f"{t[0]}-{t[1]:02d}-{t[2]:02d}_{t[3]:02d}:{t[4]:02d}:{t[5]:02d}"
    
    # --- Smooth Voltage AND Current Averaging ---
    v_sum = 0
    i_sum = 0
    for _ in range(100):
        v_sum += voltage_adc.read_u16()
        i_sum += current_adc.read_u16()
        time.sleep_us(100) 
        
    avg_v_pin = (v_sum / 100) * ADC_TO_VOLTS
    actual_voltage = avg_v_pin * VOLTAGE_DIVIDER_RATIO
    avg_i_pin = (i_sum / 100) * ADC_TO_VOLTS
    actual_current = (avg_i_pin - ACS712_OFFSET) / ACS712_SENSITIVITY
    
    # Read Temp Sensors
    sensor_error = False
    try: room_temp = round(ds_sensor.read_temp(ROOM_ADDR), 2)
    except Exception: room_temp = 0.0 
        
    try: cooler_temp = round(ds_sensor.read_temp(COOLER_ADDR), 2)
    except Exception: 
        cooler_temp = 0.0
        sensor_error = True
        
    try: exhaust_temp = round(ds_sensor.read_temp(EXHAUST_ADDR), 2)
    except Exception: 
        exhaust_temp = 0.0
        sensor_error = True

    status = "OK"
    power_percent = 0

    # --- SMART THERMOSTAT WITH PI CONTROL ---
    if sensor_error:
        status = "EMERGENCY_SHUTDOWN_SENSOR_DISCONNECTED"
        power_percent = 0
        in1.value(0)
        in2.value(0)
        integral_boost = 0.0 
        
    elif MODE == "COOL":
        in1.value(1) 
        in2.value(0)
        
        if exhaust_temp >= EXHAUST_DANGER:
            status = "EMERGENCY_SHUTDOWN_EXHAUST_OVERHEAT"
            integral_boost = 0.0
        elif cooler_temp >= COOL_MAX:
            power_percent = 100
            integral_boost = 0.0 
        elif cooler_temp <= COOL_TARGET:
            power_percent = 0
            integral_boost = 0.0 
        else:
            power_fraction = (cooler_temp - COOL_TARGET) / (COOL_MAX - COOL_TARGET)
            base_power = power_fraction * 100
            integral_boost += (cooler_temp - COOL_TARGET) * 2.0 
            if integral_boost > 50: integral_boost = 50 
                
            power_percent = int(base_power + integral_boost)
            if power_percent > 100: power_percent = 100

    elif MODE == "HEAT":
        in1.value(0) 
        in2.value(1)
        
        if cooler_temp >= NECK_DANGER:
            status = "EMERGENCY_SHUTDOWN_NECK_BURN_WARNING"
            integral_boost = 0.0
        elif cooler_temp <= HEAT_MIN:
            power_percent = 100
            integral_boost = 0.0
        elif cooler_temp >= HEAT_TARGET:
            power_percent = 0
            integral_boost = 0.0
        else:
            power_fraction = (HEAT_TARGET - cooler_temp) / (HEAT_TARGET - HEAT_MIN)
            base_power = power_fraction * 100
            integral_boost += (HEAT_TARGET - cooler_temp) * 2.0
            if integral_boost > 50: integral_boost = 50
            
            power_percent = int(base_power + integral_boost)
            if power_percent > 100: power_percent = 100
            
    if "EMERGENCY" in status:
        power_percent = 0
        
    duty_cycle = int((power_percent / 100) * 65534)
    peltier_pwm.duty_u16(duty_cycle)
    
    # Build data struct
    current_state = {
        "time": timestamp, "v": round(actual_voltage, 2), "i": round(actual_current, 2),
        "room": room_temp, "cooler": cooler_temp, "exhaust": exhaust_temp,
        "p": power_percent, "status": status, "mode": MODE
    }
    
    # Manage recent history list (keep max 20)
    recent_data.append(current_state)
    if len(recent_data) > 20:
        recent_data.pop(0)

    # Log and Print
    data_string = f"{timestamp},{actual_voltage:.2f},{actual_current:.2f},{room_temp},{cooler_temp},{exhaust_temp},{power_percent}%,{status},{MODE}"
    print(data_string)
    
    # Save to file
    try:
        file_size = os.stat(FILE_NAME)[6] 
        if file_size >= MAX_FILE_SIZE:
            os.rename(FILE_NAME, BACKUP_FILE_NAME)
            with open(FILE_NAME, "w") as file:
                file.write(HEADER)
    except OSError:
        pass 
    
    try:
        with open(FILE_NAME, "a") as file:
            file.write(data_string + "\n")
    except Exception:
        pass
    
    # Wait 1000ms while serving web pages
    wait_and_serve(1000)
