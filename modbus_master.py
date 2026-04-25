import customtkinter as ctk
import minimalmodbus
import threading
import time
import sys

SLAVE_ID = 3
PORT = 'COM25'

try:
    instrument = minimalmodbus.Instrument(PORT, SLAVE_ID)
    instrument.serial.baudrate = 115200
    instrument.serial.bytesize = 8
    instrument.serial.parity   = minimalmodbus.serial.PARITY_NONE
    instrument.serial.stopbits = 1
    instrument.serial.timeout  = 0.5
    instrument.mode = minimalmodbus.MODE_RTU
    instrument.debug = False
except:
    print("Port connection error. Closed !!!\r\n")
    sys.exit()

holding_start_addr = 4295

print(f"{PORT} is opened for MB Master\n")

try:
    while True:
        try:
            for i in range (0, 12, 1):
                value = instrument.read_register(holding_start_addr+i, 0, functioncode=3)
                print(f"{holding_start_addr+i}: {value}")
                time.sleep(0.02)
            time.sleep(0.5)
        except Exception as e:
            print(f"Error: No data: {e}")
            time.sleep(2)
except KeyboardInterrupt:
    print("Program stoppped.")
finally:
    instrument.serial.close()
    print("Port closed")
