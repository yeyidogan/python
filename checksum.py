print("Hello Python!")
def calculate_checksum(byte_list):
    total_sum = sum(byte_list)
    
    checksum = (total_sum) & 0xFF
    
    low_byte = checksum & 0xFF
    
    return low_byte

cmd_stack = [0x0A, 0x95, 0x57, 0x43, 0x5a, 0x59, 0x31, 0x00, 0x01]

ch_low = calculate_checksum(cmd_stack)

full_packet = [0x7E] + cmd_stack + [ch_low, 0xEF]

print(f"Checksum: {hex(ch_low)}")
print(f"Tam Paket (Hex): {[hex(b) for b in full_packet]}")
