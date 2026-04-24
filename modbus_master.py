import minimalmodbus
import time

SLAVE_ID = 3
PORT = 'COM11'

instrument = minimalmodbus.Instrument(PORT, SLAVE_ID)

instrument.serial.baudrate = 115200
instrument.serial.bytesize = 8
instrument.serial.parity   = minimalmodbus.serial.PARITY_NONE
instrument.serial.stopbits = 1
instrument.serial.timeout  = 0.5
instrument.mode = minimalmodbus.MODE_RTU

instrument.debug = False

print(f"{PORT} is opened for MB Master\n")

while True:
    try:
        value = instrument.read_register(2, 1, functioncode=3)
        print(f"OK, value: {value}")
        
    except Exception as e:
        print(f"Error: No data: {e}")
    
    time.sleep(2)
