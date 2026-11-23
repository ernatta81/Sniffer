#!/usr/bin/env python3
import csv
import queue
import sys
import threading
import time
from datetime import datetime

try:
    import serial
    from serial.tools import list_ports
    HAS_SERIAL = True
except Exception:
    serial = None
    list_ports = None
    HAS_SERIAL = False

try:
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, messagebox, filedialog
    HAS_TK = True
except Exception:
    HAS_TK = False


BAUD_RATES = ["300", "600", "1200", "2400", "4800", "9600", "14400", "19200",
              "28800", "38400", "57600", "76800", "115200", "128000", "230400",
              "250000", "256000", "460800", "500000", "576000", "921600",
              "1000000", "1500000", "2000000", "3000000", "4000000"]
MAX_BAUD = 20_000_000
DATA_BITS = ["5", "6", "7", "8"]
PARITIES = ["Nessuna", "Pari", "Dispari", "Mark", "Space"]
STOP_BITS = ["1", "1.5", "2"]
FLOWS = ["Nessuno", "RTS/CTS", "XON/XOFF"]

MAX_PACKETS = 20000
PREVIEW_BYTES = 128

_CTRL_NAMES = ["NUL", "SOH", "STX", "ETX", "EOT", "ENQ", "ACK", "BEL",
               "BS", "TAB", "LF", "VT", "FF", "CR", "SO", "SI",
               "DLE", "DC1", "DC2", "DC3", "DC4", "NAK", "SYN", "ETB",
               "CAN", "EM", "SUB", "ESC", "FS", "GS", "RS", "US"]
_CTRL_TABLE = {i: f"<{name}>" for i, name in enumerate(_CTRL_NAMES)}
_CTRL_TABLE[0x7F] = "<DEL>"

DIRS = ("12", "21")
OTHER = {"12": "21", "21": "12"}


def fmt_time(t, with_date=False):
    fmt = "%Y-%m-%d %H:%M:%S.%f" if with_date else "%H:%M:%S.%f"
    return datetime.fromtimestamp(t).strftime(fmt)[:-3]


def fmt_ms(ms, sign=False):
    if ms is None:
        return ""
    s = "+" if sign and ms >= 0 else ""
    if abs(ms) < 10000:
        return f"{s}{ms:.0f} ms"
    return f"{s}{ms / 1000.0:.1f} s"


def to_ascii(b):
    return bytes(b).decode("latin-1").translate(_CTRL_TABLE)


def to_hex(b):
    return bytes(b).hex(" ").upper()


class Packet:
    __slots__ = ("n", "d", "start", "end", "data", "dt", "reply_to", "latency", "replies")

    def __init__(self, n, d, t):
        self.n = n
        self.d = d
        self.start = t
        self.end = t
        self.data = bytearray()
        self.dt = None
        self.reply_to = None
        self.latency = None
        self.replies = []

    @property
    def iid(self):
        return str(self.n)


class SnifferApp:

    def __init__(self, root):
        self.root = root
        root.title("RS232 Sniffer / Bridge")
        root.geometry("1280x760")
        root.minsize(980, 560)

        self.ser = {"1": None, "2": None}
        self.threads = []
        self._running = False
        self._connected = False
        self.q = queue.Queue()

        self._fwd = {"12": True, "21": True}
        self._bytes = {"12": 0, "21": 0}
        self._fwd_err = {"12": 0, "21": 0}

        self._paused = False
        self._autoscroll = True
        self._pkts = {}
        self._n = 0
        self._open = {}
        self._last_pkt = {}
        self._last_any = None
        self._npk = {"12": 0, "21": 0}
        self._hl = []

        self._build_ui()
        self.root.after(50, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        style = ttk.Style(self.root)

        settings = ttk.LabelFrame(self.root, text="Porte seriali")
        settings.pack(fill="x", padx=8, pady=(6, 2))
        heads = ["", "Nome apparato", "Porta", "Baud (anche libero)", "Bit dati", "Parità",
                 "Bit stop", "Flusso"]
        for c, h in enumerate(heads):
            ttk.Label(settings, text=h).grid(row=0, column=c, sticky="w", padx=4, pady=(2, 0))

        self.cfg = {}
        self.cb_port = {}
        for r, key in enumerate(("1", "2"), start=1):
            v = {
                "name": tk.StringVar(value=f"Seriale {key}"),
                "port": tk.StringVar(value=""),
                "baud": tk.StringVar(value="9600"),
                "data": tk.StringVar(value="8"),
                "parity": tk.StringVar(value="Nessuna"),
                "stop": tk.StringVar(value="1"),
                "flow": tk.StringVar(value="Nessuno"),
            }
            self.cfg[key] = v
            ttk.Label(settings, text=f"Seriale {key}",
                      font=("TkDefaultFont", 9, "bold")).grid(row=r, column=0, sticky="w", padx=4)
            ent = ttk.Entry(settings, textvariable=v["name"], width=16)
            ent.grid(row=r, column=1, padx=4, pady=2, sticky="w")
            ent.bind("<FocusOut>", lambda e: self._refresh_dir_labels())
            ent.bind("<Return>", lambda e: self._refresh_dir_labels())
            self.cb_port[key] = ttk.Combobox(settings, textvariable=v["port"], width=16)
            self.cb_port[key].grid(row=r, column=2, padx=4, pady=2, sticky="w")
            widgets = [
                ttk.Combobox(settings, textvariable=v["baud"], values=BAUD_RATES, width=10,
                             height=len(BAUD_RATES)),
                ttk.Combobox(settings, textvariable=v["data"], values=DATA_BITS, width=4,
                             state="readonly"),
                ttk.Combobox(settings, textvariable=v["parity"], values=PARITIES, width=9,
                             state="readonly"),
                ttk.Combobox(settings, textvariable=v["stop"], values=STOP_BITS, width=4,
                             state="readonly"),
                ttk.Combobox(settings, textvariable=v["flow"], values=FLOWS, width=10,
                             state="readonly"),
            ]
            for c, w in enumerate(widgets, start=3):
                w.grid(row=r, column=c, padx=4, pady=2, sticky="w")

        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=8, pady=(4, 0))
        self.btn_connect = ttk.Button(bar, text="Connetti", command=self.connect)
        self.btn_connect.pack(side="left", padx=(0, 4))
        self.btn_disconnect = ttk.Button(bar, text="Disconnetti", command=self.disconnect,
                                         state="disabled")
        self.btn_disconnect.pack(side="left", padx=4)
        ttk.Button(bar, text="Aggiorna porte", command=self._refresh_ports).pack(side="left", padx=4)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        self.btn_pause = ttk.Button(bar, text="Pausa cattura", command=self._toggle_pause)
        self.btn_pause.pack(side="left", padx=4)
        ttk.Button(bar, text="Pulisci", command=self._clear).pack(side="left", padx=4)
        ttk.Button(bar, text="Esporta CSV", command=self._export_csv).pack(side="left", padx=4)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)

        self.var_fwd12 = tk.BooleanVar(value=True)
        self.var_fwd21 = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Inoltra 1 → 2", variable=self.var_fwd12,
                        command=self._sync_flags).pack(side="left", padx=4)
        ttk.Checkbutton(bar, text="Inoltra 2 → 1", variable=self.var_fwd21,
                        command=self._sync_flags).pack(side="left", padx=4)

        opt = ttk.Frame(self.root)
        opt.pack(fill="x", padx=8, pady=4)
        self.var_gap = tk.StringVar(value="50")
        self.var_timeout = tk.StringVar(value="1000")
        self.var_auto = tk.BooleanVar(value=True)
        self.var_show = {"12": tk.BooleanVar(value=True), "21": tk.BooleanVar(value=True)}

        ttk.Label(opt, text="Fine pacchetto dopo silenzio di").pack(side="left")
        ttk.Spinbox(opt, from_=0, to=10000, increment=10, width=6,
                    textvariable=self.var_gap).pack(side="left", padx=2)
        ttk.Label(opt, text="ms").pack(side="left", padx=(0, 12))
        ttk.Label(opt, text="Timeout risposta").pack(side="left")
        ttk.Spinbox(opt, from_=0, to=60000, increment=100, width=7,
                    textvariable=self.var_timeout).pack(side="left", padx=2)
        ttk.Label(opt, text="ms").pack(side="left", padx=(0, 12))
        ttk.Checkbutton(opt, text="Auto-scroll", variable=self.var_auto,
                        command=self._sync_flags).pack(side="left", padx=6)
        ttk.Separator(opt, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(opt, text="Mostra:").pack(side="left")
        self.chk_show = {}
        for d in DIRS:
            self.chk_show[d] = ttk.Checkbutton(opt, variable=self.var_show[d],
                                               command=self._apply_filter)
            self.chk_show[d].pack(side="left", padx=4)

        self.status = tk.StringVar(value="Non connesso")
        ttk.Label(self.root, textvariable=self.status, relief="sunken",
                  anchor="w").pack(fill="x", side="bottom")

        paned = ttk.Panedwindow(self.root, orient="vertical")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        list_frame = ttk.Frame(paned)
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        mono = tkfont.nametofont("TkFixedFont")
        style.configure("Sniffer.Treeview", font=mono,
                        rowheight=mono.metrics("linespace") + 4)
        def _fixed_map(option):
            return [e for e in style.map("Treeview", query_opt=option)
                    if e[:2] != ("!disabled", "!selected")]
        style.map("Sniffer.Treeview", foreground=_fixed_map("foreground"),
                  background=_fixed_map("background"))

        cols = [
            ("n", "N°", 60, "e", False),
            ("time", "Ora", 125, "w", False),
            ("dt", "Δt", 85, "e", False),
            ("dir", "Direzione", 180, "w", False),
            ("len", "Byte", 55, "e", False),
            ("resp", "Risposta a", 140, "w", False),
            ("hex", "Dati HEX", 360, "w", True),
            ("ascii", "Dati ASCII", 300, "w", True),
        ]
        self.tree = ttk.Treeview(list_frame, columns=[c[0] for c in cols], show="headings",
                                 style="Sniffer.Treeview", selectmode="browse")
        for cid, title, width, anchor, stretch in cols:
            self.tree.heading(cid, text=title, anchor=anchor)
            self.tree.column(cid, width=width, minwidth=40, anchor=anchor, stretch=stretch)
        self.tree.tag_configure("d12", background="#e3edfb")
        self.tree.tag_configure("d21", background="#e2f3e5")
        self.tree.tag_configure("link", background="#ffe27a")

        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        paned.add(list_frame, weight=4)

        detail_frame = ttk.LabelFrame(paned, text="Dettaglio pacchetto selezionato")
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        self.detail = tk.Text(detail_frame, height=9, wrap="none", font="TkFixedFont",
                              state="disabled")
        dvsb = ttk.Scrollbar(detail_frame, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=dvsb.set)
        self.detail.grid(row=0, column=0, sticky="nsew")
        dvsb.grid(row=0, column=1, sticky="ns")
        paned.add(detail_frame, weight=1)

        self._refresh_ports()
        self._refresh_dir_labels()
        self._sync_flags()

    def _name(self, key):
        return self.cfg[key]["name"].get().strip() or f"Seriale {key}"

    def _dir_label(self, d):
        return f"{self._name(d[0])} → {self._name(d[1])}"

    def _refresh_dir_labels(self):
        for d in DIRS:
            self.chk_show[d].configure(text=self._dir_label(d))
        labels = {d: self._dir_label(d) for d in DIRS}
        for iid, p in self._pkts.items():
            self.tree.set(iid, "dir", labels[p.d])

    def _sync_flags(self):
        self._fwd["12"] = bool(self.var_fwd12.get())
        self._fwd["21"] = bool(self.var_fwd21.get())
        self._autoscroll = bool(self.var_auto.get())

    @staticmethod
    def _int_var(var, default):
        try:
            return max(0, int(var.get()))
        except (ValueError, tk.TclError):
            return default

    def _refresh_ports(self):
        ports = []
        if list_ports is not None:
            try:
                ports = sorted({p.device for p in list_ports.comports()})
            except Exception:
                ports = []
        for cb in self.cb_port.values():
            cb["values"] = ports

    def _baud(self, key):
        txt = self.cfg[key]["baud"].get().strip().replace(".", "").replace(" ", "")
        try:
            baud = int(txt)
        except ValueError:
            raise ValueError(f"Seriale {key}: baud rate '{txt}' non valido, "
                             f"inserisci un numero intero (es. 115200, 250000).") from None
        if not 50 <= baud <= MAX_BAUD:
            raise ValueError(f"Seriale {key}: baud rate {baud} fuori intervallo "
                             f"(50 - {MAX_BAUD}).")
        return baud

    def _serial_kwargs(self, key):
        if not HAS_SERIAL:
            raise RuntimeError("Il modulo 'pyserial' non è installato (apt install python3-serial).")
        v = self.cfg[key]
        parity_map = {
            "Nessuna": serial.PARITY_NONE,
            "Pari": serial.PARITY_EVEN,
            "Dispari": serial.PARITY_ODD,
            "Mark": serial.PARITY_MARK,
            "Space": serial.PARITY_SPACE,
        }
        stop_map = {
            "1": serial.STOPBITS_ONE,
            "1.5": serial.STOPBITS_ONE_POINT_FIVE,
            "2": serial.STOPBITS_TWO,
        }
        data_map = {
            "5": serial.FIVEBITS,
            "6": serial.SIXBITS,
            "7": serial.SEVENBITS,
            "8": serial.EIGHTBITS,
        }
        flow = v["flow"].get()
        return {
            "port": v["port"].get().strip(),
            "baudrate": self._baud(key),
            "bytesize": data_map[v["data"].get()],
            "parity": parity_map[v["parity"].get()],
            "stopbits": stop_map[v["stop"].get()],
            "rtscts": (flow == "RTS/CTS"),
            "xonxoff": (flow == "XON/XOFF"),
            "timeout": 0.01,
        }

    def connect(self):
        if self._connected:
            return
        p1 = self.cfg["1"]["port"].get().strip()
        p2 = self.cfg["2"]["port"].get().strip()
        if not p1 or not p2:
            messagebox.showwarning("Attenzione", "Seleziona entrambe le porte seriali.")
            return
        if p1 == p2:
            messagebox.showerror("Errore", "Le due porte seriali devono essere diverse.")
            return
        try:
            kw1 = self._serial_kwargs("1")
            kw2 = self._serial_kwargs("2")
        except ValueError as e:
            messagebox.showerror("Baud rate non valido", str(e))
            return

        try:
            self.ser["1"] = serial.Serial(**kw1)
            self.ser["2"] = serial.Serial(**kw2)
        except Exception as e:
            for k in ("1", "2"):
                if self.ser[k] is not None:
                    try:
                        self.ser[k].close()
                    except Exception:
                        pass
                self.ser[k] = None
            msg = str(e)
            if getattr(e, "errno", None) == 13 or "Permission denied" in msg:
                msg += ("\n\nL'utente non ha i permessi sulla porta seriale.\n"
                        "Aggiungilo al gruppo dialout:\n"
                        "    sudo usermod -aG dialout $USER\n"
                        "poi esci dalla sessione e rientra (o riavvia).")
            messagebox.showerror("Errore apertura seriale", msg)
            return

        self._running = True
        self._connected = True
        self.threads = [
            threading.Thread(target=self._reader_loop,
                             args=("12", self.ser["1"], self.ser["2"]), daemon=True),
            threading.Thread(target=self._reader_loop,
                             args=("21", self.ser["2"], self.ser["1"]), daemon=True),
        ]
        for t in self.threads:
            t.start()

        self.btn_connect.config(state="disabled")
        self.btn_disconnect.config(state="normal")
        self._update_status()

    def disconnect(self):
        self._running = False
        self._connected = False
        for k in ("1", "2"):
            s = self.ser[k]
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
            self.ser[k] = None
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=1.0)
        self.threads = []
        self._open = {}
        self.btn_connect.config(state="normal")
        self.btn_disconnect.config(state="disabled")
        self._update_status()

    def _reader_loop(self, d, ser, other_ser):
        while self._running:
            try:
                if ser is None or not ser.is_open:
                    break
                n = ser.in_waiting
                if n > 0:
                    data = ser.read(n)
                    if data:
                        t = time.time()
                        if self._fwd[d]:
                            try:
                                other_ser.write(data)
                            except Exception:
                                self._fwd_err[d] += 1
                        self._bytes[d] += len(data)
                        self.q.put(("data", d, data, t))
                else:
                    time.sleep(0.002)
            except Exception as e:
                if self._running:
                    self.q.put(("error", d, str(e)))
                break

    def _poll_queue(self):
        changed = False
        try:
            for _ in range(5000):
                item = self.q.get_nowait()
                self._handle(item)
                changed = True
        except queue.Empty:
            pass
        if changed:
            self._update_status()
        self.root.after(30, self._poll_queue)

    def _handle(self, item):
        kind = item[0]
        if kind == "data":
            _, d, data, t = item
            if self._paused:
                return
            p = self._open.get(d)
            gap = self._int_var(self.var_gap, 50)
            if p is not None and p.iid in self._pkts and (t - p.end) * 1000.0 < gap:
                p.data += data
                p.end = t
                self._update_row(p)
            else:
                p = self._new_packet(d, t)
                p.data += data
                self._insert_row(p)
        elif kind == "error":
            _, d, msg = item
            nome = f"Seriale {d[0]} ({self._name(d[0])})"
            self.status.set(f"Errore su {nome}: {msg}")
            if self._connected:
                messagebox.showerror("Errore seriale", f"{nome}: {msg}")
                self.disconnect()

    def _new_packet(self, d, t):
        self._n += 1
        p = Packet(self._n, d, t)

        prev = self._last_any
        if prev is not None:
            p.dt = (t - prev.end) * 1000.0

        q = self._last_pkt.get(OTHER[d])
        mine = self._last_pkt.get(d)
        if q is not None and (mine is None or q.n > mine.n):
            lat = (t - q.end) * 1000.0
            tmo = self._int_var(self.var_timeout, 1000)
            if tmo == 0 or lat <= tmo:
                p.reply_to = q
                p.latency = lat
                q.replies.append(p)

        self._last_pkt[d] = p
        self._last_any = p
        self._open[d] = p
        self._npk[d] += 1
        self._pkts[p.iid] = p
        return p

    def _row_values(self, p):
        resp = ""
        if p.reply_to is not None:
            resp = f"#{p.reply_to.n}  ({fmt_ms(p.latency)})"
        prev = p.data[:PREVIEW_BYTES]
        more = " …" if len(p.data) > PREVIEW_BYTES else ""
        return (p.n, fmt_time(p.start), fmt_ms(p.dt, sign=True), self._dir_label(p.d),
                len(p.data), resp, to_hex(prev) + more, to_ascii(prev) + more)

    def _insert_row(self, p):
        self.tree.insert("", "end", iid=p.iid, values=self._row_values(p), tags=(f"d{p.d}",))
        if not self.var_show[p.d].get():
            self.tree.detach(p.iid)
        elif self._autoscroll:
            self.tree.see(p.iid)

        while len(self._pkts) > MAX_PACKETS:
            old = next(iter(self._pkts))
            del self._pkts[old]
            if self.tree.exists(old):
                self.tree.delete(old)

    def _update_row(self, p):
        if not self.tree.exists(p.iid):
            return
        self.tree.item(p.iid, values=self._row_values(p))
        sel = self.tree.selection()
        if sel and sel[0] == p.iid:
            self._show_detail(p)

    def _apply_filter(self):
        for iid, p in self._pkts.items():
            if self.var_show[p.d].get():
                self.tree.move(iid, "", "end")
            else:
                self.tree.detach(iid)
        if self._autoscroll:
            children = self.tree.get_children()
            if children:
                self.tree.see(children[-1])

    def _on_select(self, _event=None):
        for iid in self._hl:
            p = self._pkts.get(iid)
            if p is not None and self.tree.exists(iid):
                self.tree.item(iid, tags=(f"d{p.d}",))
        self._hl = []

        sel = self.tree.selection()
        p = self._pkts.get(sel[0]) if sel else None
        if p is None:
            self._set_detail("")
            return
        linked = ([p.reply_to] if p.reply_to is not None else []) + p.replies
        for q in linked:
            if q.iid in self._pkts and self.tree.exists(q.iid):
                self.tree.item(q.iid, tags=("link",))
                self._hl.append(q.iid)
        self._show_detail(p)

    def _show_detail(self, p):
        lines = [
            f"Pacchetto #{p.n}    {self._dir_label(p.d)}    {len(p.data)} byte",
            f"Inizio {fmt_time(p.start, True)}    Fine {fmt_time(p.end)}    "
            f"Δt dal pacchetto precedente: {fmt_ms(p.dt, sign=True) or '-'}",
        ]
        if p.reply_to is not None:
            lines.append(f"È la RISPOSTA al pacchetto #{p.reply_to.n} "
                         f"({self._dir_label(p.reply_to.d)}), arrivata dopo {fmt_ms(p.latency)}")
        if p.replies:
            r = ", ".join(f"#{q.n} dopo {fmt_ms(q.latency)}" for q in p.replies)
            lines.append(f"Risposta ricevuta: {r}")
        elif p.reply_to is None:
            lines.append("Nessuna risposta collegata (finora).")
        lines.append(f"Testo: {to_ascii(p.data)}")
        lines.append("")
        data = bytes(p.data)
        for off in range(0, len(data), 16):
            chunk = data[off:off + 16]
            hx = " ".join(f"{x:02X}" for x in chunk)
            asc = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
            lines.append(f"{off:04X}  {hx:<47}  {asc}")
        self._set_detail("\n".join(lines))

    def _set_detail(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def _toggle_pause(self):
        self._paused = not self._paused
        self._open = {}
        self.btn_pause.config(text="Riprendi cattura" if self._paused else "Pausa cattura")
        self._update_status()

    def _clear(self):
        if self._pkts:
            self.tree.delete(*self._pkts.keys())
        self._pkts = {}
        self._n = 0
        self._open = {}
        self._last_pkt = {}
        self._last_any = None
        self._npk = {"12": 0, "21": 0}
        self._hl = []
        self._set_detail("")
        self._update_status()

    def _export_csv(self):
        if not self._pkts:
            messagebox.showinfo("Esporta", "Non ci sono pacchetti da esportare.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=datetime.now().strftime("sniffer_%Y%m%d_%H%M%S.csv"),
            filetypes=[("CSV", "*.csv"), ("Tutti i file", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["N", "Ora", "Delta ms", "Direzione", "Byte",
                            "Risposta a", "Latenza ms", "HEX", "ASCII"])
                for p in self._pkts.values():
                    w.writerow([
                        p.n, fmt_time(p.start, True),
                        "" if p.dt is None else f"{p.dt:.1f}",
                        self._dir_label(p.d), len(p.data),
                        "" if p.reply_to is None else p.reply_to.n,
                        "" if p.latency is None else f"{p.latency:.1f}",
                        to_hex(p.data), to_ascii(p.data),
                    ])
        except Exception as e:
            messagebox.showerror("Errore esportazione", str(e))

    def _update_status(self):
        parts = []
        if self._connected:
            parts.append("Connesso")
        else:
            parts.append("Non connesso")
        if self._paused:
            parts.append("CATTURA IN PAUSA")
        for d in DIRS:
            s = f"{self._dir_label(d)}: {self._npk[d]} pacchetti, {self._bytes[d]} byte"
            if self._fwd_err[d]:
                s += f" ({self._fwd_err[d]} errori di inoltro)"
            parts.append(s)
        self.status.set("  |  ".join(parts))

    def _on_close(self):
        self.disconnect()
        self.root.destroy()


def main():
    if not HAS_TK:
        print("Errore: modulo Tkinter non disponibile.", file=sys.stderr)
        print("Installalo con:  sudo apt install python3-tk", file=sys.stderr)
        sys.exit(1)
    if not HAS_SERIAL:
        print("Errore: modulo 'pyserial' non disponibile.", file=sys.stderr)
        print("Installalo con:  sudo apt install python3-serial", file=sys.stderr)
        sys.exit(1)

    root = tk.Tk()
    SnifferApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
