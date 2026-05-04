import serial
import serial.tools.list_ports
import threading
import sys
import msvcrt
import time

# PORT = 'COM7'
PORT = 'COM25'
BAUD = 115200

ports = serial.tools.list_ports.comports()
for port in ports:
    print(f"Available Port: {port.device}")

try:
    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    print(f"--- Connected to {PORT}. Press ESC to exit ---")
except Exception as e:
    print(f"Error: {e}")
    sys.exit()

state = {"msg": "", "pos": 0, "history": [], "h_idx": -1}

def redraw():
    sys.stdout.write('\r' + '> ' + ' ' * (len(state["msg"]) + 10) + '\r')
    sys.stdout.write('> ' + state["msg"])
    back = len(state["msg"]) - state["pos"]
    if back > 0: sys.stdout.write('\b' * back)
    sys.stdout.flush()

def read_serial():
    while ser.is_open:
        try:
            if ser.in_waiting > 0:
                raw_data = ser.read(ser.in_waiting)
                data = raw_data.decode(errors='replace')
                hex_data = raw_data.hex(' ').upper()
                print(f"\r[RX HEX]: {hex_data}")
                print(f"\r[RX ASC]: {data.strip()}")
                redraw()
            else:
                time.sleep(0.02)
        except: break

threading.Thread(target=read_serial, daemon=True).start()

print("> ", end="", flush=True)

while True:
    if msvcrt.kbhit():
        ch = msvcrt.getch()
        
        # ESC to exit
        if ch == b'\x1b': break

        # Special keys
        elif ch in [b'\x00', b'\xe0']:
            ch2 = msvcrt.getch()
            if ch2 == b'K': # Left
                state["pos"] = max(0, state["pos"] - 1)
            elif ch2 == b'M': # Right
                state["pos"] = min(len(state["msg"]), state["pos"] + 1)
            elif ch2 == b'H': # Up
                if len(state["history"]) > 0 and state["h_idx"] < len(state["history"]) - 1:
                    state["h_idx"] += 1
                    state["msg"] = state["history"][-(state["h_idx"] + 1)]
                    state["pos"] = len(state["msg"])
            elif ch2 == b'P': # Down
                if state["h_idx"] > 0:
                    state["h_idx"] -= 1
                    state["msg"] = state["history"][-(state["h_idx"] + 1)]
                    state["pos"] = len(state["msg"])
                elif state["h_idx"] == 0:
                    state["h_idx"] = -1
                    state["msg"] = ""; state["pos"] = 0
            elif ch2 == b'S': # Delete
                if state["pos"] < len(state["msg"]):
                    state["msg"] = state["msg"][:state["pos"]] + state["msg"][state["pos"]+1:]
            redraw()

        # Enter
        elif ch == b'\r':
            if state["msg"].strip():
                state["history"].append(state["msg"])
            ser.write((state["msg"] + '\r\n').encode())
            print()
            state["msg"] = ""; state["pos"] = 0; state["h_idx"] = -1
            sys.stdout.write("> "); sys.stdout.flush()

        # Backspace
        elif ch == b'\x08':
            if state["pos"] > 0:
                state["msg"] = state["msg"][:state["pos"]-1] + state["msg"][state["pos"]:]
                state["pos"] -= 1
                redraw()

        else:
            try:
                char = ch.decode()
                state["msg"] = state["msg"][:state["pos"]] + char + state["msg"][state["pos"]:]
                state["pos"] += 1
                redraw()
            except: pass

ser.close()
print("\n--- Connection terminated. ---")
