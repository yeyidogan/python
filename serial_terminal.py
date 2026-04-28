import serial
import serial.tools.list_ports
import keyboard
import threading
import sys

PORT = 'COM25' 
BAUD = 115200

ports = serial.tools.list_ports.comports()
for port in ports:
    print(f"Available Port: {port.device}")

try:
    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    print(f"--- Connected to {PORT}. Press ESC to exit ---")
except:
    print(f"{PORT} cannot opened!")
    sys.exit()

tx_msg = ""

def read_from_serial():
    global tx_msg
    while ser.is_open:
        if ser.in_waiting > 0:
            data = ser.read(ser.in_waiting).decode(errors='replace')
            print(f"\r[RX]: {data.strip()}")
            print(f"> {tx_msg}", end="", flush=True)

thread_rx = threading.Thread(target=read_from_serial, daemon=True)
thread_rx.start()

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
            print("\n> ", end="", flush=True)
        elif e.name == 'backspace':
            tx_msg = tx_msg[:-1]
            print("\b \b", end="", flush=True)
        elif len(e.name) == 1:
            tx_msg += e.name
            print(e.name, end="", flush=True)
        elif e.name == 'space':
            tx_msg += " "
            print(" ", end="", flush=True)

keyboard.hook(on_key_event)

print("> ", end="", flush=True)
keyboard.wait('esc')
ser.close()
print("\nConnection terminated.")
