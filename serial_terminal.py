import serial
import serial.tools.list_ports
import keyboard
import threading
import sys
import pygetwindow as gw

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

history = []
history_index = -1

def on_key_event(e):
    global tx_msg, history, history_index 
    active_window = gw.getActiveWindow()
    if active_window is None:
        return
    window_title = active_window.title.lower()
    targets = ["terminal", "visual studio code", "code", "powershell", "cmd"]
    if not any(target in window_title for target in targets):
        return
    
    if e.event_type == keyboard.KEY_DOWN:
        if e.name == 'f1':
            #ser.write(bytes.fromhex("ffaabbcc"))
            ser.write(b"1234\r\n")

        elif e.name == 'f2':
            ser.write(b"'Hello\r\n")

        elif e.name == 'enter':
            clean_msg = tx_msg.strip()
            if clean_msg:
                history.append(clean_msg)
            ser.write((tx_msg + '\r\n').encode())
            tx_msg = ""
            history_index = -1
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
        
        elif e.name == 'up':
            if len(history) > 0 and history_index < len(history) - 1:
                history_index += 1
                print("\r> " + " " * len(tx_msg) + "\r> ", end="", flush=True)
                tx_msg = history[-(history_index + 1)]
                print(tx_msg, end="", flush=True)

        elif e.name == 'down':
            if history_index > 0:
                history_index -= 1
                print("\r> " + " " * len(tx_msg) + "\r> ", end="", flush=True)
                tx_msg = history[-(history_index + 1)]
                print(tx_msg, end="", flush=True)
            elif history_index == 0:
                history_index = -1
                print("\r> " + " " * len(tx_msg) + "\r> ", end="", flush=True)
                tx_msg = ""

keyboard.hook(on_key_event)

print("> ", end="", flush=True)
keyboard.wait('esc')
ser.close()
print("\nConnection terminated.")
