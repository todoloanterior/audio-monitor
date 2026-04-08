#!/bin/bash
cd "$(dirname "$0")"

# Check Python is installed
if ! command -v python3 &>/dev/null; then
    echo ""
    echo "  ERROR: Python no esta instalado."
    echo "  Pide a Santiago que ejecute setup.sh primero."
    echo ""
    read -p "  Presiona Enter para cerrar..."
    exit 1
fi

# Auto-install dependencies if missing
python3 -c "import sounddevice, numpy" 2>/dev/null || {
    echo "  Instalando dependencias..."
    pip3 install -r requirements.txt --quiet 2>/dev/null
}

# Run the monitor
python3 monitor.py

# Keep window open if it crashed
if [ $? -ne 0 ]; then
    echo ""
    echo "  El monitor se cerro con un error."
    echo "  Asegurate de que Rode Connect este abierto."
    read -p "  Presiona Enter para cerrar..."
fi
