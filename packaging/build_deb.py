#!/usr/bin/env python3
import hashlib
import io
import os
import sys
import tarfile
import time

PACKAGE = "rs232-sniffer"
VERSION = "1.0.0"
MAINTAINER = os.environ.get("DEB_MAINTAINER", "Sesami")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

LAUNCHER = """#!/bin/sh
exec /usr/bin/python3 /usr/share/rs232-sniffer/sniffer_rs232.py "$@"
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=RS232 Sniffer
GenericName=Sniffer seriale RS232
Comment=Sniffer e ponte tra due porte seriali RS232
Exec=rs232-sniffer
Icon=utilities-system-monitor
Terminal=false
Categories=Utility;Development;
"""

POSTINST = """#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    echo ""
    echo "RS232 Sniffer installato. Avvio: rs232-sniffer (o dal menu applicazioni)."
    echo "Per usare le porte seriali senza root l'utente deve essere nel gruppo dialout:"
    echo "    sudo usermod -aG dialout \\$USER    (poi esci e riaccedi)"
    echo ""
fi
exit 0
"""


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def files_to_install():
    return [
        ("usr/share/rs232-sniffer/sniffer_rs232.py",
         read_text(os.path.join(ROOT, "sniffer_rs232.py")), 0o644),
        ("usr/bin/rs232-sniffer", LAUNCHER, 0o755),
        ("usr/share/applications/rs232-sniffer.desktop", DESKTOP, 0o644),
        ("usr/share/doc/rs232-sniffer/README.md",
         read_text(os.path.join(ROOT, "README.md")), 0o644),
    ]


def add_entry(tar, name, data=None, mode=0o644, mtime=None):
    info = tarfile.TarInfo(name)
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = mtime
    if data is None:
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        tar.addfile(info)
    else:
        info.mode = mode
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def make_tar_gz(entries, mtime):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for name, data, mode in entries:
            add_entry(tar, name, data, mode, mtime)
    return buf.getvalue()


def ar_member(name, data, mtime):
    header = (f"{name:<16}{mtime:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n").encode("ascii")
    assert len(header) == 60
    pad = b"\n" if len(data) % 2 else b""
    return header + data + pad


def build():
    mtime = int(time.time())
    files = [(path, content.encode("utf-8"), mode) for path, content, mode in files_to_install()]

    dirs = set()
    for path, _, _ in files:
        parts = path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    data_entries = [("./", None, None)]
    data_entries += [(f"./{d}/", None, None) for d in sorted(dirs)]
    data_entries += [(f"./{p}", c, m) for p, c, m in files]

    installed_kb = max(1, sum(len(c) for _, c, _ in files) // 1024)
    control = (
        f"Package: {PACKAGE}\n"
        f"Version: {VERSION}\n"
        "Section: utils\n"
        "Priority: optional\n"
        "Architecture: all\n"
        "Depends: python3 (>= 3.8), python3-tk, python3-serial\n"
        f"Installed-Size: {installed_kb}\n"
        f"Maintainer: {MAINTAINER}\n"
        "Description: Sniffer e ponte RS232 con interfaccia grafica\n"
        " Si collega in linea tra due apparati tramite due porte seriali,\n"
        " ritrasmette i dati in entrambi i versi e mostra il traffico come lista\n"
        " cronologica di pacchetti, collegando ogni risposta al suo comando.\n"
    )
    md5sums = "".join(f"{hashlib.md5(c).hexdigest()}  {p}\n" for p, c, _ in files)
    control_entries = [
        ("./", None, None),
        ("./control", control.encode("utf-8"), 0o644),
        ("./md5sums", md5sums.encode("utf-8"), 0o644),
        ("./postinst", POSTINST.encode("utf-8"), 0o755),
    ]

    deb = b"!<arch>\n"
    deb += ar_member("debian-binary", b"2.0\n", mtime)
    deb += ar_member("control.tar.gz", make_tar_gz(control_entries, mtime), mtime)
    deb += ar_member("data.tar.gz", make_tar_gz(data_entries, mtime), mtime)

    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, f"{PACKAGE}_{VERSION}_all.deb")
    with open(out, "wb") as f:
        f.write(deb)
    return out


if __name__ == "__main__":
    path = build()
    print(f"Creato: {path} ({os.path.getsize(path)} byte)")
    sys.exit(0)
