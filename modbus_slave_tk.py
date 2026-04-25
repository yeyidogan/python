import serial
import modbus_tk.defines as cst
from modbus_tk import modbus_rtu
import random
import time
import sys

SLAVE_ID = 3
PORT = 'COM24'

try:
    ser = serial.Serial(port=PORT, baudrate=115200)
except:
    print("Port connection error. Closed !!!\r\n")
    sys.exit()
    
server = modbus_rtu.RtuServer(ser)

slave_mb = server.add_slave(SLAVE_ID)
print("Slave running... Ctrl+C to stop!!\r\n")
server.start()

holding_start_addr = 4295
slave_mb.add_block('block1', cst.HOLDING_REGISTERS, holding_start_addr, 12)
slave_mb.add_block('coil', cst.COILS, 1, 10)
slave_mb.set_values('coil', 1, 1)   # 00001 = ON (1)
slave_mb.set_values('coil', 2, 0)   # 00002 = OFF (0)
try:
    while True:
        for i in range(0, 12, 1):
            rnd = random.randint(0, 65536)
            slave_mb.set_values('block1', holding_start_addr+i, rnd)
        time.sleep(1)
except KeyboardInterrupt:
    print("Program stop..\­r\n")
finally:
    server.stop()
    ser.close()
