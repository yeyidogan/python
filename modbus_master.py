import customtkinter as ctk
import minimalmodbus
import threading
import time
import sys

SLAVE_ID = 3
#PORT = 'COM25'
PORT = '/dev/ttyUSB0'

try:
    instrument = minimalmodbus.Instrument(PORT, SLAVE_ID)
    instrument.serial.baudrate = 115200
    instrument.serial.bytesize = 8
    instrument.serial.parity   = minimalmodbus.serial.PARITY_NONE
    instrument.serial.stopbits = 1
    instrument.serial.timeout  = 0.1
    instrument.mode = minimalmodbus.MODE_RTU
    instrument.debug = False
except Exception as e:
    print(f"Port connection error: {e} \r\n")
    input("Press any key...")
    sys.exit()

holding_start_addr = 4295

#print(f"{PORT} is opened for MB Master\n")
class ModbusGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Modbus Register Monitor & Alarm")
        self.geometry("500x500")

        self.error_cnt = [0] * 10
        self.error_labels = []
        self.answer_cnt = [0] * 10
        self.answer_labels = []
        self.value_labels = []
        #self.label_title = ctk.CTkLabel(self, text="Holding Registers (4295-4304)", font=("Arial", 18, "bold"))
        #self.label_title.pack(pady=20)
        self.mb_reg_LED = 0

        self.alarm_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.alarm_frame.pack(pady=10, fill="x", padx=40)
        self.alarm_status = ctk.CTkLabel(self.alarm_frame, text="Running Normally", 
                                        font=("Arial", 16, "bold"), 
                                        text_color="green",
                                        fg_color="#2b2b2b", height=40, corner_radius=8)
        self.alarm_status.pack(fill="x")

        for i in range(10):
            frame = ctk.CTkFrame(self)
            frame.pack(pady=2, fill="x", padx=40)
            
            addr_label = ctk.CTkLabel(frame, text=f"{i+1} Reg {4296+i}:", width=80, anchor="w", text_color="#052850")
            addr_label.pack(side="left", padx=10)
            
            val_label = ctk.CTkLabel(frame, text="0", font=("Arial", 14, "bold"), text_color="#1f538d")
            val_label.pack(side="right", padx=20)
            self.value_labels.append(val_label)

            answer_label = ctk.CTkLabel(frame, text="Answer: 0", font=("Arial", 12), text_color="green")
            answer_label.pack(side="right", padx=10)
            self.answer_labels.append(answer_label)

            err_label = ctk.CTkLabel(frame, text="Error: 0", font=("Arial", 12), text_color="gray")
            err_label.pack(side="right", padx=10)
            self.error_labels.append(err_label)

        self.err_msg_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.err_msg_frame.pack(pady=10, fill="x", padx=40)
        self.err_msg_frame_status = ctk.CTkLabel(self.err_msg_frame, text="Modbus exception messages", 
                                        font=("Arial", 14), text_color="green",
                                        wraplength=400, justify = "left")
        self.err_msg_frame_status.pack(fill="x")
        
        # read thread
        self.update_thread = threading.Thread(target=self.read_modbus, daemon=True)
        self.update_thread.start()   

    def check_alarm(self, reg_addr, reg_value):
        if reg_value >= 10000:
            self.alarm_status.configure(text=f"⚠️ OVER RANGE! (Reg {reg_addr})", 
                                        text_color="white", fg_color="#922b21")
        #else:
        #    self.alarm_status.configure(text="Running Normally", text_color="white")

    def read_modbus(self):
        while True:
            for i in range (0, 10, 1):
                try:
                    value = instrument.read_register(holding_start_addr+i, 0, functioncode=3)
                    self.value_labels[i].configure(text=str(value))
                    #print(f"{holding_start_addr+i}: {value}")
                    self.answer_cnt[i] += 1
                    self.answer_labels[i].configure(text=f"Answer: {self.answer_cnt[i]}", text_color="green")
                    self.check_alarm(holding_start_addr+i, value)
                    time.sleep(0.002)
                except Exception as e:
                    #print(f"Error: No data: {e}")
                    self.error_cnt[i] += 1
                    self.error_labels[i].configure(text=f"Error: {self.error_cnt[i]}", text_color="red")
                    self.value_labels[i].configure(text="N/A", text_color="red")
                    self.err_msg_frame_status.configure(text=f"Exception code: {e} "
                                                        f"at request # {holding_start_addr+i+1}.")
                    #time.sleep(0.5)
            time.sleep(0.01)
            if self.mb_reg_LED == 0:
                try:
                    instrument.write_register(4307, 0x00, functioncode=6)
                    time.sleep(0.002)
                    instrument.write_register(4308, 0x00, functioncode=6)
                    time.sleep(0.002)
                    instrument.write_register(4309, 0x01, functioncode=6)
                    self.mb_reg_LED = 1
                except:
                    print("Holding write 0x0000 error !")
            else:
                try:
                    instrument.write_register(4307, 0xFFFF, functioncode=6)
                    time.sleep(0.005)
                    instrument.write_register(4308, 0xFFFF, functioncode=6)
                    time.sleep(0.005)
                    instrument.write_register(4309, 0x02, functioncode=6)
                    self.mb_reg_LED = 0
                except:
                    print("Holding write 0xFFFF error !")
            time.sleep(0.01)



if __name__ == "__main__":
    app = ModbusGUI()
    app.mainloop()
