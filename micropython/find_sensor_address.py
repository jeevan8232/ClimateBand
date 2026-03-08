import machine
import onewire
import ds18x20
import time

ds_pin = machine.Pin(15)
ds_sensor = ds18x20.DS18X20(onewire.OneWire(ds_pin))

roms = ds_sensor.scan()
print(f"Found {len(roms)} sensors.")

for i, rom in enumerate(roms):
    ds_sensor.convert_temp()
    time.sleep_ms(750)
    temp = ds_sensor.read_temp(rom)
    # This prints the exact code you need to copy
    print(f"Sensor {i} Address: {rom} | Current Temp: {temp:.2f} C")