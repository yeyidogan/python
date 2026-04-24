import serial
import modbus_tk.defines as cst
from modbus_tk import modbus_rtu
import random

SLAVE_ID = 3
PORT = 'COM12'

ser = serial.Serial(port=PORT, baudrate=115200)

server = modbus_rtu.RtuServer(ser)

slave_mb = server.add_slave(SLAVE_ID)

slave_mb.add_block('block1', cst.HOLDING_REGISTERS, 1, 10)
slave_mb.set_values('block1', 1, 60123)
rnd = random.randint(0, 65536)
slave_mb.set_values('block1', 2, rnd)

slave_mb.add_block('coil', cst.COILS, 1, 10)
slave_mb.set_values('coil', 1, 1)   # 00001 = ON (1)
slave_mb.set_values('coil', 2, 0)   # 00002 = OFF (0)

print("Slave running... Ctrl+C to stop!!\r\n")
server.start()
