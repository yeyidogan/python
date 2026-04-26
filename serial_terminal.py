import serial
import serial.tools.list_ports
import keyboard
import threading

PORT = 'COM25' 
BAUD = 115200

ports = serial.tools.list_ports.comports()
for port in ports:
    print(f"Available Port: {port.device}")

try:
    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    print(f"--- {PORT} connected. Write and press Enter ---")
except:
    print(f"{PORT} cannot opened!")
    exit()

tx_msg = ""

def on_key_event(e):
    global tx_msg
    if e.event_type == keyboard.KEY_DOWN:
        if e.name == 'f1':
            ser.write(b"1234\r\n")
        elif e.name == 'f2':
            ser.write(b"'Hello\r\n")
        elif e.name == 'enter':
            ser.write((tx_msg + '\r\n').encode())
            tx_msg = ""
        elif e.name == 'backspace':
            tx_msg = tx_msg[:-1]
            print(f"\r> {tx_msg} ", end="", flush=True)
        elif len(e.name) > 0:
            tx_msg += e.name
            print(e.name, end="", flush=True)

keyboard.hook(on_key_event)

print("> ", end="", flush=True)
keyboard.wait('esc')
ser.close()
print("\nConnection terminated.")
