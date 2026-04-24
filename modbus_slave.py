import serial
import time
import random

SLAVE_ID = 3
PORT = 'COM12'
ser = serial.Serial(PORT, 115200, timeout=0.5)

print(f"Python Modbus Slave Listening {PORT}...")

def calculate_crc(data):
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for i in range(8):
            if (crc & 1) != 0:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, 'little')

try:
    while True:
        time.sleep(0.02)
        request = ser.read(8)
        if len(request) >= 8:
            print(f"Received request: {request.hex().upper()}")
            
            if request[0] == 3 and request[1] == 3:
                # ID(1), Func(3), ByteCount(2), Value(00 37 = 55), CRC
                response_data = bytearray([SLAVE_ID, 0x03, 0x02, 0x00, 0x37])
                crc = calculate_crc(response_data)
                full_response = response_data + crc
                
                ser.write(full_response)
                print(f"Transmitted answer: {full_response.hex().upper()}")

except KeyboardInterrupt:
    print("Program stoppped.")
finally:
    ser.close()
    print("Slave closed.")
