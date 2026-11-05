#!/usr/bin/env python3
"""Mini CANopen Analyzer (PCAN-USB)
Install: pip install python-can   (+ PEAK PCAN driver / PCAN-Basic)
Run: python canopen_mini.py
For Linux SocketCAN: set INTERFACE = "socketcan" and channel = "can0".
"""
import configparser, csv, json, queue, re, struct, threading, time
from collections import deque
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import can

INTERFACE = "pcan"
MAX_LOG_ROWS = 100000
MAX_TREE_ROWS = 5000
CONFIG_PATH = Path.home() / ".canopen_mini.ini"
BITRATES = {"1000k": 1000000, "500k": 500000, "250k": 250000, "125k": 125000,
            "50k": 50000, "20k": 20000, "10k": 10000}
NMT_CMDS = {"Start": 0x01, "Stop": 0x02, "Pre-Op": 0x80, "Reset Node": 0x81, "Reset Comm": 0x82}
NMT_STATE = {0: "Boot-up", 4: "Stopped", 5: "Operational", 127: "Pre-Operational"}
FRAME_KINDS = ("All", "NMT", "SYNC", "EMCY", "TPDO", "RPDO", "SDO", "Heartbeat", "LSS", "Other")
TYPE_FMT = {0x01: ("?", 1), 0x02: ("b", 1), 0x03: ("h", 2), 0x04: ("i", 4), 0x05: ("B", 1),
            0x06: ("H", 2), 0x07: ("I", 4), 0x08: ("f", 4), 0x15: ("q", 8), 0x1B: ("Q", 8)}


def num(s, default=0):
    try:
        return int(str(s).strip(), 0)
    except ValueError:
        return default


def hexnum(s, default=None):  # CANopen convention: 'aa', '1800', and '0x1800' are all hexadecimal
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

    def tpdo_map(self, n):  # EDS default mapping; the device's active mapping may differ
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


def frame_kind(description):
    for kind in FRAME_KINDS[1:-1]:
        if description.startswith(kind):
            return kind
    return "Other"


def matches_filter(record, query="", direction="All", kind="All"):
    if direction != "All" and record[2] != direction:
        return False
    if kind != "All" and frame_kind(record[6]) != kind:
        return False
    return query.casefold() in " ".join(map(str, record[1:])).casefold()


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
            return f"SDO READ RESPONSE {idx} = {val}" if d[0] & 2 else f"SDO READ RESPONSE {idx} (segmented)"
        return f"SDO WRITE OK {idx}" if ccs == 3 else "SDO segment data"
    if ccs == 1:
        return f"SDO WRITE {idx} = {val} (0x{val:X})"
    return f"SDO READ {idx}" if ccs == 2 else "SDO segment request"


def decode(msg, eds, node, tpdo_mapping=None):
    cid, d = msg.arbitration_id, bytes(msg.data)
    if msg.is_error_frame:
        return "CAN error frame"
    if msg.is_remote_frame:
        return "RTR"
    if cid == 0 and len(d) >= 2:
        name = next((k for k, v in NMT_CMDS.items() if v == d[0]), hex(d[0]))
        return f"NMT {name} -> {'ALL NODES' if d[1] == 0 else 'Node ' + str(d[1])}"
    if cid == 0x80:
        return "SYNC"
    if 0x81 <= cid <= 0xFF and len(d) >= 3:
        return f"EMCY Node {cid - 0x80} code=0x{d[0] | d[1] << 8:04X} reg=0x{d[2]:02X}"
    for n, (tb, rb) in enumerate(((0x180, 0x200), (0x280, 0x300), (0x380, 0x400), (0x480, 0x500))):
        if tb < cid <= tb + 127:
            txt = f"TPDO{n + 1} Node {cid - tb}"
            if tpdo_mapping is not None or (eds and cid - tb == node):
                pos, parts = 0, []
                mapping = tpdo_mapping if tpdo_mapping is not None else eds.tpdo_map(n)
                for idx, sub, bits in mapping:
                    chunk = d[pos:pos + bits // 8]
                    pos += bits // 8
                    o = eds.lookup(idx, sub) if eds else {}
                    parts.append(f"{o.get('name') or hex(idx)}={unpack_value(o, chunk)}")
                if parts:
                    txt += ": " + ", ".join(parts)
            return txt
        if rb < cid <= rb + 127:
            return f"RPDO{n + 1} Node {cid - rb}"
    if 0x581 <= cid <= 0x5FF or 0x601 <= cid <= 0x67F:
        resp = cid < 0x600
        return f"SDO {'response' if resp else 'request'} Node {cid - (0x580 if resp else 0x600)}: {decode_sdo(d, resp)}"
    if 0x701 <= cid <= 0x77F and d:
        return f"Heartbeat Node {cid - 0x700}: {NMT_STATE.get(d[0] & 0x7F, d[0])}"
    if cid in (0x7E4, 0x7E5):
        return "LSS"
    return ""


class Link:
    def __init__(self):
        self.bus, self.rx, self.sdo, self.errors, self.run, self.th = None, queue.Queue(), queue.Queue(), queue.Queue(), False, None

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
            try:
                m = self.bus.recv(0.1)
            except can.CanError as e:
                self.errors.put(str(e))
                self.run = False
                break
            if m:
                self.rx.put((time.time(), "Rx", m))
                if 0x581 <= m.arbitration_id <= 0x5FF:
                    self.sdo.put(m)

    def send(self, cid, data):
        msg = can.Message(arbitration_id=cid, data=data, is_extended_id=False)
        self.bus.send(msg)
        self.rx.put((time.time(), "Tx", msg))  # Include transmitted frames in the trace.

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
        while True:  # Segmented transfer.
            r = self.txn(node, bytes([0x60 | (t << 4)]) + bytes(7))
            if r[0] >> 5 or ((r[0] >> 4) & 1) != t:
                raise IOError("Unexpected SDO segment response")
            out += r[1:1 + 7 - ((r[0] >> 1) & 7)]
            if r[0] & 1:
                return out
            t ^= 1

    def read_tpdo_map(self, node, number):
        idx = 0x1A00 + number - 1
        count_data = self.sdo_read(node, idx, 0)
        if not 1 <= len(count_data) <= 4:
            raise IOError(f"Invalid TPDO{number} mapping count")
        count = int.from_bytes(count_data, "little")
        if count > 64:
            raise IOError(f"TPDO{number} mapping count exceeds 64")
        mapping = []
        total_bits = 0
        for sub in range(1, count + 1):
            data = self.sdo_read(node, idx, sub)
            if len(data) != 4:
                raise IOError(f"Invalid TPDO{number} mapping at subindex {sub}")
            entry = int.from_bytes(data, "little")
            bits = entry & 0xFF
            if bits == 0 or bits % 8:
                raise IOError(f"TPDO{number} has unsupported {bits}-bit mapping")
            total_bits += bits
            if total_bits > 64:
                raise IOError(f"TPDO{number} mapping exceeds the 8-byte CAN payload")
            mapping.append(((entry >> 16) & 0xFFFF, (entry >> 8) & 0xFF, bits))
        return mapping

    def sdo_write(self, node, idx, sub, data):
        if not 1 <= len(data) <= 4:
            raise ValueError("This version only supports writes of 1-4 bytes")
        cmd = 0x23 | ((4 - len(data)) << 2)
        response = self.txn(node, struct.pack("<BHB", cmd, idx, sub) + data.ljust(4, b"\0"), expected=(idx, sub))
        if response[0] != 0x60:
            raise IOError("Unexpected SDO download response")


class App:
    def __init__(s):
        s.link, s.eds, s.rows, s.t0 = Link(), None, deque(maxlen=MAX_LOG_ROWS), None
        s.tpdo_maps, s.paused = {}, False
        s.settings_error = None
        settings = configparser.ConfigParser()
        try:
            settings.read(CONFIG_PATH, encoding="utf-8")
        except (OSError, configparser.Error) as e:
            s.settings_error = str(e)
        saved = settings["connection"] if settings.has_section("connection") else {}
        r = s.root = tk.Tk()
        r.title("Mini CANopen Analyzer - PCAN-USB")
        r.geometry("1150x680")
        s.ch, s.br = tk.StringVar(value=saved.get("channel", "PCAN_USBBUS1")), tk.StringVar(value=saved.get("bitrate", "125k"))
        s.node, s.idx, s.sub = tk.StringVar(value="20"), tk.StringVar(value="1000"), tk.StringVar(value="0")
        s.size, s.val, s.res = tk.StringVar(value="auto"), tk.StringVar(), tk.StringVar()
        s.sdo_results, s.sdo_busy = queue.Queue(), False
        s.filter_text = tk.StringVar()
        s.filter_direction = tk.StringVar(value="All")
        s.filter_kind = tk.StringVar(value="All")
        s.tpdo_num = tk.StringVar(value="1")

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
        btn(f, "Load EDS", s.load_eds)
        s.map_btn = ttk.Button(f, text="Read TPDO map", command=s.read_tpdo_map)
        s.map_btn.pack(side="left", padx=2)
        ttk.Combobox(f, textvariable=s.tpdo_num, values=["1", "2", "3", "4"], width=3, state="readonly").pack(side="left")
        btn(f, "CSV Export", s.save_csv); btn(f, "JSON Export", s.save_json); btn(f, "Clear", s.clear)
        s.pause_btn = ttk.Button(f, text="Pause", command=s.toggle_pause)
        s.pause_btn.pack(side="left", padx=2)
        f = row()
        lab(f, "Filter"); ent(f, s.filter_text, 32)
        ttk.Combobox(f, textvariable=s.filter_direction, values=["All", "Rx", "Tx"], width=5, state="readonly").pack(side="left")
        ttk.Combobox(f, textvariable=s.filter_kind, values=FRAME_KINDS, width=11, state="readonly").pack(side="left")
        btn(f, "Apply", s.refresh_trace)
        f = row()
        lab(f, "Node ID (hex)"); ent(f, s.node, 5)
        for name, code in NMT_CMDS.items():
            btn(f, name, lambda c=code: s.nmt(c))
        f = row()
        lab(f, "SDO Index (hex)"); ent(f, s.idx, 9); lab(f, "Sub (hex)"); ent(f, s.sub, 4)
        lab(f, "Bytes"); ttk.Combobox(f, textvariable=s.size, values=["auto", "1", "2", "4"], width=5, state="readonly").pack(side="left")
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
        if s.settings_error:
            r.after_idle(lambda: messagebox.showwarning("Settings", f"Could not load settings: {s.settings_error}"))

    def nid(s): return hexnum(s.node.get(), -1)

    def toggle(s):
        if s.link.bus:
            try:
                s.link.close()
            except can.CanError as e:
                messagebox.showerror("Disconnect Error", str(e))
            s.cbtn.config(text="Connect"); return
        try:
            s.link.open(s.ch.get(), BITRATES[s.br.get()]); s.cbtn.config(text="Disconnect")
        except Exception as e:
            messagebox.showerror("Connection Error", f"{e}\n\nCheck PCAN driver!")

    def need_bus(s, sdo=False):
        if not s.link.bus:
            messagebox.showwarning("Unconnected", "Connect before."); return False
        lo = 1 if sdo else 0
        if not lo <= s.nid() <= 127:
            messagebox.showwarning("Node ID", f"Enter a hexadecimal node ID in the range {lo:X}-7F (e.g. 5, 10, 7F)."); return False
        return True

    def nmt(s, code):
        if s.need_bus():
            try:
                s.link.send(0, bytes([code, s.nid()]))  # Node 0 broadcasts to all nodes.
            except can.CanError as e:
                messagebox.showerror("Send Error", str(e))

    def read_tpdo_map(s):
        if not s.need_bus(True): return
        node, number = s.nid(), int(s.tpdo_num.get())

        def work():
            mapping = s.link.read_tpdo_map(node, number)
            return f"TPDO{number} device mapping read ({len(mapping)} entries)", {(node, number - 1): mapping}

        s.start_sdo(work)

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
            s.res.set("Index/Subindex must be hexadecimal (e.g. 1800 and 5)"); return None
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
        access = str(o.get("acc", "")).strip().lower()
        if access and access not in ("rw", "wo"):
            s.res.set(f"EDS access type '{access}' does not allow writing")
            return
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
        for button in (s.cbtn, s.read_btn, s.write_btn, s.map_btn):
            button.state(["disabled"])

        def run():
            try:
                result = work()
            except queue.Empty:
                s.sdo_results.put(("Timeover (no answer)", None))
            except Exception as e:
                s.sdo_results.put((str(e), None))
            else:
                s.sdo_results.put(result if isinstance(result, tuple) else (result, None))

        threading.Thread(target=run, daemon=True).start()

    def poll(s):
        try:
            result, maps = s.sdo_results.get_nowait()
        except queue.Empty:
            pass
        else:
            s.sdo_busy = False
            s.res.set(result)
            if maps:
                s.tpdo_maps.update(maps)
                s.refresh_trace()
            for button in (s.cbtn, s.read_btn, s.write_btn, s.map_btn):
                button.state(["!disabled"])
        try:
            error = s.link.errors.get_nowait()
        except queue.Empty:
            pass
        else:
            s.link.close()
            s.cbtn.config(text="Connect")
            messagebox.showerror("CAN Receive Error", error)
        for _ in range(300):
            try: ts, way, m = s.link.rx.get_nowait()
            except queue.Empty: break
            s.t0 = s.t0 or ts
            mapping_number = next(
                (number for number, (base, _) in enumerate(((0x180, 0x200), (0x280, 0x300), (0x380, 0x400), (0x480, 0x500)))
                 if base < m.arbitration_id < base + 128),
                None,
            )
            mapping = s.tpdo_maps.get((s.nid(), mapping_number)) if mapping_number is not None else None
            txt = decode(m, s.eds, s.nid(), mapping)
            record = (ts, f"{ts - s.t0:.3f}", way, f"{m.arbitration_id:03X}", m.dlc, bytes(m.data).hex(" ").upper(), txt)
            s.rows.append(record)
            if not s.paused and matches_filter(record, s.filter_text.get(), s.filter_direction.get(), s.filter_kind.get()):
                s.insert_trace(record)
        s.root.after(50, s.poll)

    def insert_trace(s, record):
        tag = "abort" if "ABORT" in record[6] else ("tx" if record[2] == "Tx" else "")
        s.tr.see(s.tr.insert("", "end", values=record[1:], tags=(tag,)))
        kids = s.tr.get_children()
        if len(kids) > MAX_TREE_ROWS: s.tr.delete(kids[0])

    def refresh_trace(s):
        s.tr.delete(*s.tr.get_children())
        if not s.paused:
            selected = [
                record for record in reversed(s.rows)
                if matches_filter(record, s.filter_text.get(), s.filter_direction.get(), s.filter_kind.get())
            ][:MAX_TREE_ROWS]
            for record in reversed(selected):
                s.insert_trace(record)

    def toggle_pause(s):
        s.paused = not s.paused
        s.pause_btn.config(text="Resume" if s.paused else "Pause")
        if not s.paused:
            s.refresh_trace()

    def clear(s):
        s.rows.clear(); s.t0 = None; s.tr.delete(*s.tr.get_children())

    def save_csv(s):
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if p:
            records = [r for r in s.rows if matches_filter(r, s.filter_text.get(), s.filter_direction.get(), s.filter_kind.get())]
            try:
                with open(p, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["timestamp", "elapsed_s", "direction", "cob_id", "dlc", "data", "decoded", "channel", "bitrate"])
                    for record in records:
                        w.writerow([datetime.fromtimestamp(record[0]).astimezone().isoformat(timespec="milliseconds"), *record[1:], s.ch.get(), s.br.get()])
            except OSError as e:
                messagebox.showerror("Export Error", str(e))

    def save_json(s):
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if p:
            records = [r for r in s.rows if matches_filter(r, s.filter_text.get(), s.filter_direction.get(), s.filter_kind.get())]
            data = {
                "metadata": {"channel": s.ch.get(), "bitrate": s.br.get()},
                "frames": [
                    {"timestamp": datetime.fromtimestamp(r[0]).astimezone().isoformat(timespec="milliseconds"),
                     "elapsed_s": r[1], "direction": r[2], "cob_id": r[3], "dlc": r[4], "data": r[5], "decoded": r[6]}
                    for r in records
                ],
            }
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except OSError as e:
                messagebox.showerror("Export Error", str(e))

    def quit(s):
        if s.sdo_busy:
            messagebox.showwarning("Operation in progress", "Wait for the SDO operation to finish.")
            return
        if s.link.bus:
            try:
                s.link.close()
            except can.CanError as e:
                messagebox.showerror("Disconnect Error", str(e))
        settings = configparser.ConfigParser()
        settings["connection"] = {"channel": s.ch.get(), "bitrate": s.br.get()}
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                settings.write(f)
        except OSError as e:
            messagebox.showerror("Settings Error", f"Could not save settings: {e}")
        s.root.destroy()


if __name__ == "__main__":
    App().root.mainloop()