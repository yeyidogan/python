import os
import re
import subprocess
import sys

def get_windows_wifi():
    try:
        interfaces = subprocess.check_output("netsh wlan show interfaces", shell=True).decode('utf-8', errors='ignore')
        ssid_match = re.search(r"SSID\s*:\s*(.*)", interfaces)
        if not ssid_match:
            return None, None
        ssid = ssid_match.group(1).strip()
        
        profile = subprocess.check_output(f'netsh wlan show profile name="{ssid}" key=clear', shell=True).decode('utf-8', errors='ignore')
        password_match = re.search(r"Key Content\s*:\s*(.*)", profile)
        if not password_match:
            password_match = re.search(r"Anahtar İçeriği\s*:\s*(.*)", profile)
            
        password = password_match.group(1).strip() if password_match else ""
        return ssid, password
    except Exception as e:
        print(f"Windows Wi-Fi could not read: {e}")
        return None, None

def get_mac_wifi():
    try:
        ssid_cmd = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I"
        airport = subprocess.check_output(ssid_cmd, shell=True).decode('utf-8')
        ssid_match = re.search(r" SSID: (.*)", airport)
        if not ssid_match:
            return None, None
        ssid = ssid_match.group(1).strip()
        
        password_cmd = f"security find-generic-password -D 'AirPort network password' -a '{ssid}' -w"
        password = subprocess.check_output(password_cmd, shell=True).decode('utf-8').strip()
        return ssid, password
    except Exception as e:
        print(f"Mac Wi-Fi could not read: {e}")
        return None, None

def main():
    print("Scanning Sistem Wi-Fi ...")
    if sys.platform.startswith('win'):
        ssid, password = get_windows_wifi()
    elif sys.platform.startswith('darwin'):
        ssid, password = get_mac_wifi()
    else:
        print("Unsupported OS.")
        return

    if not ssid:
        print("Could not found any wi-fi connection!")
        return

    print(f"Found connection: {ssid}")
    
    current_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
    file_path = os.path.join(current_dir, "wificonfig.txt")
    
    # Raspberry Pi OS (Bookworm) format
    config_content = f"ssid={ssid}\npsk={password}\ncountry=TR\n"
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(config_content)
        print("Wi-Fi read OK")
        print(f"File path: {file_path}")
    except Exception as e:
        print(f"File write error: {e}")

if __name__ == "__main__":
    main()
