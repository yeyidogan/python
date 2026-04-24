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

try:
    while True:
        try:
            value = instrument.read_register(1, 0, functioncode=3)
            print(f"40001: {value}")
            time.sleep(0.1)
            value = instrument.read_register(2, 0, functioncode=3)
            print(f"40002: {value}")
            time.sleep(0.1)
            val_coil = instrument.read_bit(1, functioncode=1)
            print(f"Coil 00001: {val_coil}")
            time.sleep(0.5)
        except Exception as e:
            print(f"Error: No data: {e}")
            time.sleep(2)
except KeyboardInterrupt:
    print("Program stoppped.")
finally:
    instrument.serial.close()
    print("Port closed")
