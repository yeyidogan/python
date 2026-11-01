#!/usr/bin/env python3
"""Mini CANopen Analyzer (PCAN-USB)
Kurulum: pip install python-can   (+ PEAK PCAN sürücüsü / PCAN-Basic)
Çalıştırma: python canopen_mini.py
Linux SocketCAN için: INTERFACE = "socketcan", kanal "can0".
"""
import configparser, csv, queue, re, struct, threading, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import can

INTERFACE = "pcan"
BITRATES = {"1000k": 1000000, "500k": 500000, "250k": 250000, "125k": 125000,
            "50k": 50000, "20k": 20000, "10k": 10000}
NMT_CMDS = {"Start": 0x01, "Stop": 0x02, "Pre-Op": 0x80, "Reset Node": 0x81, "Reset Comm": 0x82}
NMT_STATE = {0: "Boot-up", 4: "Stopped", 5: "Operational", 127: "Pre-Operational"}
TYPE_FMT = {0x01: ("?", 1), 0x02: ("b", 1), 0x03: ("h", 2), 0x04: ("i", 4), 0x05: ("B", 1),
            0x06: ("H", 2), 0x07: ("I", 4), 0x08: ("f", 4), 0x15: ("q", 8), 0x1B: ("Q", 8)}


def num(s, default=0):
    try:
        return int(str(s).strip(), 0)
    except ValueError:
        return default


def hexnum(s, default=None):  # CANopen alışkanlığı: 'aa', '1800', '0x1800' hepsi hex
    try:
        return int(str(s).strip(), 16)
    except ValueError:
        return default


class EDS:
    def __init__(self, path):
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        cp.read(path, encoding="latin-1")
        self.objs = {}  # (index, sub|None) -> dict
        for sec in cp.sections():
            m = re.fullmatch(r"([0-9A-Fa-f]{4})(?:sub([0-9A-Fa-f]+))?", sec)
            if not m:
                continue
            d = cp[sec]
            key = (int(m[1], 16), int(m[2], 16) if m[2] else None)
            self.objs[key] = dict(name=d.get("ParameterName", ""), type=num(d.get("DataType", "0")),
                                  acc=d.get("AccessType", ""), default=d.get("DefaultValue", ""))

    def lookup(self, idx, sub):
        return self.objs.get((idx, sub)) or self.objs.get((idx, None)) or {}

    def tpdo_map(self, n):  # EDS'teki VARSAYILAN mapping (cihazdaki gerçek değer farklı olabilir)
        cnt = num(self.objs.get((0x1A00 + n, 0), {}).get("default", ""))
        out = []
        for i in range(1, cnt + 1):
            v = num(self.objs.get((0x1A00 + n, i), {}).get("default", ""))
            out.append((v >> 16, (v >> 8) & 0xFF, v & 0xFF))
        return out


def unpack_value(o, data):
    f = TYPE_FMT.get(o.get("type"))
    if o.get("type") == 0x09:
        return data.decode("ascii", "replace")
    if f and len(data) == f[1]:
        return struct.unpack("<" + f[0], data)[0]
    return int.from_bytes(data, "little") if 0 < len(data) <= 8 else data.hex()


def encode_value(o, value, size):
    if not 1 <= size <= 4:
        raise ValueError("Expedited SDO writes must be 1-4 bytes")
    type_code = o.get("type")
    fmt = TYPE_FMT.get(type_code)
    if type_code == 0x09:
        raise ValueError("String SDO writes are not supported")
    if fmt:
        code, expected_size = fmt
        if expected_size != size:
            raise ValueError(f"EDS type requires {expected_size} bytes")
        if code == "f":
            parsed = float(value.strip())
        else:
            parsed = num(value, None)
            if parsed is None:
                raise ValueError("Enter a valid integer value")
            if code == "?" and parsed not in (0, 1):
                raise ValueError("Boolean values must be 0 or 1")
        try:
            return struct.pack("<" + code, parsed)
        except (OverflowError, struct.error) as e:
            raise ValueError(f"Value does not fit the EDS type: {e}") from e
    if type_code not in (None, 0):
        raise ValueError(f"EDS datatype 0x{type_code:02X} is not supported for writes")
    parsed = num(value, None)
    if parsed is None:
        raise ValueError("Enter a valid integer value")
    try:
        return parsed.to_bytes(size, "little", signed=False)
    except OverflowError as e:
        raise ValueError(f"Value does not fit in {size} bytes") from e


def decode_sdo(d, resp):
    if not d:
        return ""
    if d[0] == 0x80 and len(d) >= 8:
        return f"ABORT 0x{struct.unpack('<I', d[4:8])[0]:08X}"
    ccs = d[0] >> 5
    idx = f"0x{d[1] | d[2] << 8:04X}/{d[3]}" if len(d) >= 4 else ""
    n = 4 - ((d[0] >> 2) & 3) if d[0] & 1 else 4
    val = int.from_bytes(d[4:4 + n], "little")
    if resp:
        if ccs == 2:
            return f"OKUMA YANITI {idx} = {val}" if d[0] & 2 else f"OKUMA YANITI {idx} (segmentli)"
        return f"YAZMA OK {idx}" if ccs == 3 else "segment verisi"
    if ccs == 1:
        return f"YAZ {idx} = {val} (0x{val:X})"
    return f"OKU {idx}" if ccs == 2 else "segment isteği"


def decode(msg, eds, node):
    cid, d = msg.arbitration_id, bytes(msg.data)
    if msg.is_remote_frame:
        return "RTR"
    if cid == 0 and len(d) >= 2:
        name = next((k for k, v in NMT_CMDS.items() if v == d[0]), hex(d[0]))
        return f"NMT {name} -> {'TÜMÜ' if d[1] == 0 else 'Node ' + str(d[1])}"
    if cid == 0x80:
        return "SYNC"
    if 0x81 <= cid <= 0xFF and len(d) >= 3:
        return f"EMCY Node {cid - 0x80} kod=0x{d[0] | d[1] << 8:04X} reg=0x{d[2]:02X}"
    for n, (tb, rb) in enumerate(((0x180, 0x200), (0x280, 0x300), (0x380, 0x400), (0x480, 0x500))):
        if tb < cid <= tb + 127:
            txt = f"TPDO{n + 1} Node {cid - tb}"
            if eds and cid - tb == node:
                pos, parts = 0, []
                for idx, sub, bits in eds.tpdo_map(n):
                    chunk = d[pos:pos + bits // 8]
                    pos += bits // 8
                    o = eds.lookup(idx, sub)
                    parts.append(f"{o.get('name') or hex(idx)}={unpack_value(o, chunk)}")
                if parts:
                    txt += ": " + ", ".join(parts)
            return txt
        if rb < cid <= rb + 127:
            return f"RPDO{n + 1} Node {cid - rb}"
    if 0x581 <= cid <= 0x5FF or 0x601 <= cid <= 0x67F:
        resp = cid < 0x600
        return f"SDO {'yanıt' if resp else 'istek'} Node {cid - (0x580 if resp else 0x600)}: {decode_sdo(d, resp)}"
    if 0x701 <= cid <= 0x77F and d:
        return f"Heartbeat Node {cid - 0x700}: {NMT_STATE.get(d[0] & 0x7F, d[0])}"
    if cid in (0x7E4, 0x7E5):
        return "LSS"
    return ""


class Link:
    def __init__(self):
        self.bus, self.rx, self.sdo, self.run, self.th = None, queue.Queue(), queue.Queue(), False, None

    def open(self, channel, bitrate):
        self.bus = can.Bus(interface=INTERFACE, channel=channel, bitrate=bitrate)
        self.run = True
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    def close(self):
        self.run = False
        if self.th:
            self.th.join(1)
        if self.bus:
            self.bus.shutdown()
        self.bus = None

    def _loop(self):
        while self.run:
            m = self.bus.recv(0.1)
            if m:
                self.rx.put((time.time(), "Rx", m))
                if 0x581 <= m.arbitration_id <= 0x5FF:
                    self.sdo.put(m)

    def send(self, cid, data):
        msg = can.Message(arbitration_id=cid, data=data, is_extended_id=False)
        self.bus.send(msg)
        self.rx.put((time.time(), "Tx", msg))  # gönderilenler de trace'te görünsün

    def txn(self, node, payload, timeout=1.0, expected=None):
        while not self.sdo.empty():
            self.sdo.get_nowait()
        self.send(0x600 + node, payload)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            m = self.sdo.get(timeout=remaining)
            if m.arbitration_id != 0x580 + node:
                continue
            d = bytes(m.data)
            if len(d) != 8:
                raise IOError("Malformed SDO response")
            if expected and (int.from_bytes(d[1:3], "little"), d[3]) != expected:
                continue
            if d[0] == 0x80:
                raise IOError(f"SDO abort 0x{struct.unpack('<I', d[4:8])[0]:08X}")
            return d

    def sdo_read(self, node, idx, sub):
        d = self.txn(node, struct.pack("<BHB4x", 0x40, idx, sub), expected=(idx, sub))
        if d[0] >> 5 != 2:
            raise IOError("Unexpected SDO upload response")
        if d[0] & 0x02:  # expedited
            return d[4:4 + (4 - ((d[0] >> 2) & 3) if d[0] & 1 else 4)]
        out, t = b"", 0
        while True:  # segmented
            r = self.txn(node, bytes([0x60 | (t << 4)]) + bytes(7))
            if r[0] >> 5 or ((r[0] >> 4) & 1) != t:
                raise IOError("Unexpected SDO segment response")
            out += r[1:1 + 7 - ((r[0] >> 1) & 7)]
            if r[0] & 1:
                return out
            t ^= 1

    def sdo_write(self, node, idx, sub, data):
        if not 1 <= len(data) <= 4:
            raise ValueError("Bu sürüm yalnızca 1-4 bayt yazar")
        cmd = 0x23 | ((4 - len(data)) << 2)
        response = self.txn(node, struct.pack("<BHB", cmd, idx, sub) + data.ljust(4, b"\0"), expected=(idx, sub))
        if response[0] != 0x60:
            raise IOError("Unexpected SDO download response")


class App:
    def __init__(s):
        s.link, s.eds, s.rows, s.t0 = Link(), None, [], None
        r = s.root = tk.Tk()
        r.title("Mini CANopen Analyzer - PCAN-USB")
        r.geometry("1150x680")
        s.ch, s.br = tk.StringVar(value="PCAN_USBBUS1"), tk.StringVar(value="125k")
        s.node, s.idx, s.sub = tk.StringVar(value="20"), tk.StringVar(value="1000"), tk.StringVar(value="0")
        s.size, s.val, s.res = tk.StringVar(value="auto"), tk.StringVar(), tk.StringVar()
        s.sdo_results, s.sdo_busy = queue.Queue(), False

        def row():
            f = ttk.Frame(r)
            f.pack(fill="x", padx=6, pady=3)
            return f

        def lab(f, t): ttk.Label(f, text=t).pack(side="left", padx=(8, 2))
        def ent(f, v, w=8): ttk.Entry(f, textvariable=v, width=w).pack(side="left")
        def btn(f, t, c): ttk.Button(f, text=t, command=c).pack(side="left", padx=2)

        f = row()
        lab(f, "Channel"); ent(f, s.ch, 14)
        lab(f, "Speed"); ttk.Combobox(f, textvariable=s.br, values=list(BITRATES), width=7, state="readonly").pack(side="left")
        s.cbtn = ttk.Button(f, text="Connect", command=s.toggle)
        s.cbtn.pack(side="left", padx=6)
        btn(f, "Load EDS", s.load_eds); btn(f, "CSV Export", s.save_csv); btn(f, "Clear", s.clear)
        f = row()
        lab(f, "Node ID (hex)"); ent(f, s.node, 5)
        for name, code in NMT_CMDS.items():
            btn(f, name, lambda c=code: s.nmt(c))
        f = row()
        lab(f, "SDO Index (hex)"); ent(f, s.idx, 9); lab(f, "Sub (hex)"); ent(f, s.sub, 4)
        lab(f, "Bayt"); ttk.Combobox(f, textvariable=s.size, values=["auto", "1", "2", "4"], width=5, state="readonly").pack(side="left")
        lab(f, "Value (dec / 0x)"); ent(f, s.val, 14)
        s.read_btn = ttk.Button(f, text="Read", command=s.read)
        s.read_btn.pack(side="left", padx=2)
        s.write_btn = ttk.Button(f, text="Write", command=s.write)
        s.write_btn.pack(side="left", padx=2)
        ttk.Label(f, textvariable=s.res, foreground="#0a5").pack(side="left", padx=10)

        body = ttk.PanedWindow(r, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6, pady=4)
        s.od = ttk.Treeview(body, columns=("name", "acc"), height=20)
        s.od.heading("#0", text="OD (EDS)"); s.od.heading("name", text="Name"); s.od.heading("acc", text="Access")
        s.od.column("#0", width=90); s.od.column("name", width=200); s.od.column("acc", width=50)
        s.od.bind("<Double-1>", s.pick)
        body.add(s.od, weight=1)
        s.tr = ttk.Treeview(body, columns=("t", "dir", "id", "dlc", "data", "dec"), show="headings")
        s.tr.tag_configure("tx", foreground="#0050c8"); s.tr.tag_configure("abort", foreground="#c00000")
        for c, t, w in (("t", "Time", 70), ("dir", "Dir", 40), ("id", "COB-ID", 60), ("dlc", "DLC", 40), ("data", "Data", 190), ("dec", "Description", 420)):
            s.tr.heading(c, text=t); s.tr.column(c, width=w, anchor="w")
        body.add(s.tr, weight=3)
        r.protocol("WM_DELETE_WINDOW", s.quit)
        r.after(50, s.poll)

    def nid(s): return hexnum(s.node.get(), -1)

    def toggle(s):
        if s.link.bus:
            s.link.close(); s.cbtn.config(text="Bağlan"); return
        try:
            s.link.open(s.ch.get(), BITRATES[s.br.get()]); s.cbtn.config(text="Disconnect")
        except Exception as e:
            messagebox.showerror("Connection Error", f"{e}\n\nCheck PCAN driver!")

    def need_bus(s, sdo=False):
        if not s.link.bus:
            messagebox.showwarning("Unconnected", "Connect before."); return False
        lo = 1 if sdo else 0
        if not lo <= s.nid() <= 127:
            messagebox.showwarning("Node ID", f"Node ID hex and {lo:X}-7F aralığında (örn: 5, 10, 7F)."); return False
        return True

    def nmt(s, code):
        if s.need_bus(): s.link.send(0, bytes([code, s.nid()]))  # node 0 = tümü

    def load_eds(s):
        p = filedialog.askopenfilename(filetypes=[("EDS", "*.eds *.EDS"), ("All", "*.*")])
        if not p: return
        s.eds = EDS(p)
        s.od.delete(*s.od.get_children())
        for idx in sorted({k[0] for k in s.eds.objs}):
            o = s.eds.objs.get((idx, None)) or s.eds.objs.get((idx, 0), {})
            s.od.insert("", "end", iid=f"{idx:04X}_", text=f"0x{idx:04X}", values=(o.get("name", ""), o.get("acc", "")))
            for sub in sorted(k[1] for k in s.eds.objs if k[0] == idx and k[1] is not None):
                so = s.eds.objs[(idx, sub)]
                s.od.insert(f"{idx:04X}_", "end", iid=f"{idx:04X}_{sub}", text=f"sub {sub}", values=(so["name"], so["acc"]))

    def pick(s, _e):
        iid = s.od.focus()
        if "_" in iid:
            i, sub = iid.split("_")
            s.idx.set(i); s.sub.set(sub or "0")

    def target(s):
        idx, sub = hexnum(s.idx.get()), hexnum(s.sub.get())
        if idx is None or sub is None:
            s.res.set("Index/Sub hex olmalı (örn: 1800 ve 5)"); return None
        return idx, sub, (s.eds.lookup(idx, sub) if s.eds else {})

    def read(s):
        if not s.need_bus(True): return
        t = s.target()
        if not t: return
        idx, sub, o = t
        node = s.nid()

        def work():
            d = s.link.sdo_read(node, idx, sub)
            return f"{d.hex(' ').upper()}  =  {unpack_value(o, d)}"

        s.start_sdo(work)

    def write(s):
        if not s.need_bus(True): return
        t = s.target()
        if not t: return
        idx, sub, o = t
        try:
            n = int(s.size.get()) if s.size.get() != "auto" else (TYPE_FMT.get(o.get("type"), (0, 4))[1])
            data = encode_value(o, s.val.get(), n)
        except Exception as e:
            s.res.set(str(e))
            return
        node = s.nid()

        def work():
            s.link.sdo_write(node, idx, sub, data)
            return "Written (OK)"

        s.start_sdo(work)

    def start_sdo(s, work):
        if s.sdo_busy:
            return
        s.sdo_busy = True
        s.res.set("Working...")
        for button in (s.cbtn, s.read_btn, s.write_btn):
            button.state(["disabled"])

        def run():
            try:
                result = work()
            except queue.Empty:
                s.sdo_results.put("Timeover (no answer)")
            except Exception as e:
                s.sdo_results.put(str(e))
            else:
                s.sdo_results.put(result)

        threading.Thread(target=run, daemon=True).start()

    def poll(s):
        try:
            result = s.sdo_results.get_nowait()
        except queue.Empty:
            pass
        else:
            s.sdo_busy = False
            s.res.set(result)
            for button in (s.cbtn, s.read_btn, s.write_btn):
                button.state(["!disabled"])
        for _ in range(300):
            try: ts, way, m = s.link.rx.get_nowait()
            except queue.Empty: break
            s.t0 = s.t0 or ts
            txt = decode(m, s.eds, s.nid())
            row = (f"{ts - s.t0:.3f}", way, f"{m.arbitration_id:03X}", m.dlc, bytes(m.data).hex(" ").upper(), txt)
            s.rows.append(row)
            tag = "abort" if "ABORT" in txt else ("tx" if way == "Tx" else "")
            s.tr.see(s.tr.insert("", "end", values=row, tags=(tag,)))
            kids = s.tr.get_children()
            if len(kids) > 5000: s.tr.delete(kids[0])
        s.root.after(50, s.poll)

    def clear(s):
        s.rows.clear(); s.t0 = None; s.tr.delete(*s.tr.get_children())

    def save_csv(s):
        p = filedialog.asksaveasfilename(defaultextension=".csv")
        if p:
            with open(p, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["time", "dir", "id", "dlc", "data", "decoded"]); w.writerows(s.rows)

    def quit(s):
        if s.sdo_busy:
            messagebox.showwarning("Operation in progress", "Wait for the SDO operation to finish.")
            return
        if s.link.bus: s.link.close()
        s.root.destroy()


if __name__ == "__main__":
    App().root.mainloop()