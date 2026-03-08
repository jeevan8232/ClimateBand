
# ClimateBand 🌡️❄️

**A Smart, Wearable Neck AC & Heater powered by Raspberry Pi Pico W**

ClimateBand is an open-source, wearable thermal device that provides direct-to-skin cooling and heating. Using a Thermoelectric Peltier module, it mimics the "AC effect" of high-end commercial wearables by using physical conduction to lower or raise your body temperature.

It features a custom PI (Proportional-Integral) thermostat, smooth PWM control, and emergency fail-safes.

## How It Works

Unlike a room air conditioner that cools the air (convection), ClimateBand cools your skin directly (conduction). The cold side of a Peltier module presses against an aluminum neck plate. As blood flows past this cold plate, your entire body feels a massive temperature drop. By reversing the polarity of the current, the device instantly transforms into a winter neck heater.

---

## Hardware Requirements

* **Microcontroller:** Raspberry Pi Pico W
* **Thermal Engine:** TEC1-12706 Peltier Module
* **Motor Driver:** L298N Motor Driver *(Note: Upgrade to DRV8871 or XY-160D MOSFET driver highly recommended—see "Known Issues" below)*
* **Sensors:** 3x DS18B20 One-Wire Temperature Sensors
* **Power Monitoring:** ACS712 Current Sensor (20A version) & Voltage Divider module
* **Cooling System:** Small 5V exhaust fan & lightweight aluminum heatsink
* **Neck Interface:** Smooth aluminum or copper plate
* **Misc:** SPDT Toggle Switch, Thermal Paste, 5V High-Output Power Bank (Minimum 3A output)

---

## Wiring & Connections

### L298N Motor Driver (H-Bridge)

* **ENA (PWM):** Pico GP14 (Remove jumper cap)
* **IN1:** Pico GP13
* **IN2:** Pico GP12
* **OUT1:** Peltier Red Wire
* **OUT2:** Peltier Black Wire
* **Power:** 5V Power Supply (+) to 12V Terminal, GND to GND (Share ground with Pico)

### Sensors & Inputs

* **DS18B20 Data Line(3 data lines to 1 pin:** Pico GP16 (Requires one 4.7k pull-up resistor from data line to VCC:3.3V)
* **Voltage Sensor (Analog):** Pico GP26 (ADC0) VCC: 3.3v (max 16v meassurement)
* **ACS712 Current Sensor (Analog):** Pico GP27 (ADC1) VCC: 5V connect to vbus
* **Mode Toggle Switch:** Center pin to Pico GP15, Outer pin to GND.

---

## Safety Features (Fail-Safes)

Because this device straps a heating/cooling element directly to the human body, safety was the primary design focus. The software includes hardcoded cutoffs:

1. **Sensor Disconnect Protection:** If a sensor wire breaks or disconnects, the system defaults to `0.0` or throws an exception. The code catches this and instantly kills power to the driver to prevent blind overheating.
2. **Exhaust Overheat:** If the cooling fan fails and the hot side reaches 45°C, the system triggers an `EMERGENCY_SHUTDOWN`.
3. **Neck Burn Warning:** In "HEAT" mode, if the neck plate reaches 45°C, power is instantly cut.

---

## ⚠️ Development Journey & Issues Solved

If you are replicating this build, you will likely run into the same physics and software hurdles we faced. Here is how we solved them:

### 1. The "12V Thermal Runaway" Problem

**Issue:** We initially tested the TEC module at 12V to get maximum cooling. However, the hot side generated so much heat that a wearable-sized exhaust fan couldn't keep up. The heat bled back through the ceramic, actually making the *cold* side warmer (reaching 26.5°C).
**Solution:** We scaled the system down to **5V**. At 5V, the Peltier still drops to an icy 16.8°C, but the waste heat generated is small enough to be exhausted by a tiny, wearable fan.

### 2. The MicroPython 100% PWM Bug

**Issue:** The cooling power was stalling because whenever the PWM hit 100% (`65535`), the voltage would mysteriously drop to 0.1V, shutting the cooler off.
**Solution:** This is a known hardware/firmware rollover bug in some Pico boards. We limited the maximum PWM duty cycle to `65534`, completely preventing the rollover and keeping the cooler on.

### 3. Sensor "Strobing" from PWM Noise

**Issue:** Voltage and current readings were wildly fluctuating (e.g., current jumping between 0.15A and 1.14A every second).
**Solution:** The sensors were taking instantaneous 1-microsecond snapshots, randomly catching the PWM square wave at its peak or its valley. We wrapped the analog reads in a 10-millisecond, 100-sample `for` loop to accurately average out the PWM wave.

### 4. The Steady-State Error Wall

**Issue:** The neck plate would cool rapidly down to 20.25°C but refuse to reach the 18°C target. The proportional control calculated a 45% power requirement, which perfectly matched the ambient heat leak, resulting in an equilibrium where the temperature never changed.
**Solution:** We implemented a **PI (Proportional-Integral) Controller**.

By adding an `integral_boost` variable, the software acts like a timer. The longer the temperature remains stuck above the target, the more it artificially "boosts" the PWM power (pushing it to 55%, 60%, etc.) until it breaks through the thermal wall.

### 5. The L298N Voltage Drop (The "Hidden Tax")

**Issue:** The Peltier module wasn't getting enough power.
**Solution:** The L298N uses inefficient Darlington Pair transistors, which consume roughly 1.5V to 2.0V internally as waste heat. If you supply 5V, the Peltier only sees ~3.2V.

* *Quick fix:* Supply 7V to the L298N (if isolated from the Pico).
* *Permanent fix:* Swap the L298N for a modern MOSFET driver like the **DRV8871** or **XY-160D**, which have a near-zero voltage drop, sending the full 5V directly to the cooler.

### 6. ACS712 Current Sensor Calibration

**Issue:** Current readings were exactly double the actual multimeter readings (reading 1.4A when it was actually 0.7A).
**Solution:** Analog sensors require absolute precision. We had to calibrate two things:

1. **Offset:** We found our USB bank was outputting slightly more than 5V, changing the resting sensor voltage from exactly `2.500V` to `2.522V`.
2. **Sensitivity:** We discovered we were using the 20A version of the ACS712, not the 30A version. We updated the code's sensitivity multiplier from `0.066` to `0.100` (100mV/A).

---

## How to Run

1. Wire components according to the wiring instructions.
2. Update your `WIFI_SSID` and `WIFI_PASSWORD` in `main.py` for NTP time syncing.
3. Discover your specific DS18B20 ROM addresses and update `ROOM_ADDR`, `COOLER_ADDR`, and `EXHAUST_ADDR`. By executing find_sensor_address.py 
4. Run the code via Thonny. Data will automatically log to `data_log.csv` onboard the Pico.
