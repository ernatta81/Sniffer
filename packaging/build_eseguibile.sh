#!/bin/sh
set -e

cd "$(dirname "$0")/.."

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-tk binutils

python3 -m venv .venv-build
. .venv-build/bin/activate
pip install --upgrade pip
pip install pyinstaller pyserial

pyinstaller --noconfirm --clean --onefile --windowed \
    --name rs232-sniffer \
    --hidden-import serial.tools.list_ports \
    --distpath dist --workpath build --specpath build \
    sniffer_rs232.py

deactivate

echo ""
echo "Eseguibile creato: $(pwd)/dist/rs232-sniffer"
echo "Avvio: ./dist/rs232-sniffer"
