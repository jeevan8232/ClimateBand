import machine
import onewire
import ds18x20
import time
import network
import ntptime
import os

# --- Wi-Fi & Time Setup ---
WIFI_SSID = "YOUR_WIFI_NAME"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
IST_OFFSET = 19800 

print("Connecting to Wi-Fi...")
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID, WIFI_PASSWORD)

max_wait = 10
while max_wait > 0:
    if wlan.status() < 0 or wlan.status() >= 3:
        break
    max_wait -= 1
    time.sleep(1)

if wlan.status() == 3:
    try:
        ntptime.settime() 
        ist_epoch = time.time() + IST_OFFSET
        tm = time.localtime(ist_epoch)
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
    except Exception:
        pass

# --- Setup Sensors, Controls & Switches ---
ds_pin = machine.Pin(16)
ds_sensor = ds18x20.DS18X20(onewire.OneWire(ds_pin))
voltage_adc = machine.ADC(26)
current_adc = machine.ADC(27)

peltier_pwm = machine.PWM(machine.Pin(14)) 
peltier_pwm.freq(1000)
peltier_pwm.duty_u16(0)

in1 = machine.Pin(13, machine.Pin.OUT)
in2 = machine.Pin(12, machine.Pin.OUT)

# NEW: Setup the Mode Toggle Switch on GP15
# Using PULL_UP means it reads '1' normally, and '0' when the switch is closed to Ground.
mode_switch = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_UP)

# --- Constants & Calibration ---
ADC_TO_VOLTS = 3.3 / 65535
VOLTAGE_DIVIDER_RATIO = 5.0 
ACS712_OFFSET = 2.522  # Calibrated Offset
ACS712_SENSITIVITY = 0.100  # 20A Sensor Sensitivity

# Sensor Addresses (UPDATE THESE)
ROOM_ADDR = bytearray(b'(\xf9\xa6u\xd0\x01<\xbc') #Run the other code to find your sensor addresses
COOLER_ADDR = bytearray(b'(\x8f\xfcu\xd0\x01<\xbe') 
EXHAUST_ADDR = bytearray(b'(\xd8\x7fu\xd0\x01<\x90') 

FILE_NAME = "data_log.csv"
BACKUP_FILE_NAME = "data_log_backup.csv"
HEADER = "time,voltage,current,roomtemp,coolertemp,exhusttemp,cooling_power,status,mode\n"
MAX_FILE_SIZE = 512000 

# ==========================================
# --- SMART CLIMATEBAND SETTINGS ---
# Mode is now handled by the physical switch!

# Cooling Settings
COOL_TARGET = 18.0    
COOL_MAX = 23.0       
EXHAUST_DANGER = 45.0 

# Heating Settings
HEAT_TARGET = 38.0    
HEAT_MIN = 33.0       
NECK_DANGER = 45.0    
# ==========================================

try:
    with open(FILE_NAME, "r") as file:
        pass
except OSError:
    with open(FILE_NAME, "w") as file:
        file.write(HEADER)

print(HEADER.strip())

integral_boost = 0.0

while True:
    # --- Read Physical Switch for Mode ---
    if mode_switch.value() == 0:
        MODE = "HEAT"
    else:
        MODE = "COOL"
        
    ds_sensor.convert_temp()
    time.sleep_ms(750) 
        
    t = time.localtime()
    timestamp = f"{t[0]}-{t[1]:02d}-{t[2]:02d}_{t[3]:02d}:{t[4]:02d}:{t[5]:02d}"
    
    # Smooth Voltage AND Current Averaging (10ms sample)
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
    
    # Read Temp Sensors & Check for disconnects
    sensor_error = False
    try: room_temp = ds_sensor.read_temp(ROOM_ADDR)
    except Exception: room_temp = 0.0 
        
    try: cooler_temp = ds_sensor.read_temp(COOLER_ADDR)
    except Exception: 
        cooler_temp = 0.0
        sensor_error = True
        
    try: exhaust_temp = ds_sensor.read_temp(EXHAUST_ADDR)
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
    
    # Log and Print Data
    data_string = f"{timestamp},{actual_voltage:.2f},{actual_current:.2f},{room_temp:.2f},{cooler_temp:.2f},{exhaust_temp:.2f},{power_percent}%,{status},{MODE}"
    print(data_string)
    
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