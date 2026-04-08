#!/bin/bash
#
# Audio Monitor — One-time setup for Mac
# Run this once on Felipe's Mac: bash setup.sh
#

set -e

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║     AUDIO MONITOR — SETUP (Mac)      ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Step 1: Check/install Homebrew ──
echo "  [1/6] Checking Homebrew..."
if command -v brew &>/dev/null; then
    echo "         Homebrew OK"
else
    echo "         Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for Apple Silicon Macs
    if [ -f /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    echo "         Homebrew installed"
fi

# ── Step 2: Install Python 3 ──
echo "  [2/6] Checking Python 3..."
if command -v python3 &>/dev/null; then
    PYVER=$(python3 --version 2>&1)
    echo "         $PYVER OK"
else
    echo "         Installing Python 3..."
    brew install python3
    echo "         Python 3 installed"
fi

# ── Step 3: Install ffmpeg ──
echo "  [3/6] Checking ffmpeg..."
if command -v ffmpeg &>/dev/null; then
    echo "         ffmpeg OK"
else
    echo "         Installing ffmpeg..."
    brew install ffmpeg
    echo "         ffmpeg installed"
fi

# ── Step 4: Install Python dependencies ──
echo "  [4/6] Installing Python packages..."
pip3 install -r requirements.txt --quiet 2>/dev/null
echo "         sounddevice, numpy, scipy OK"

# ── Step 5: Make launcher executable ──
echo "  [5/6] Setting up launcher..."
chmod +x start-monitor.command
echo "         start-monitor.command ready (double-click to run)"

# ── Step 6: Test ──
echo "  [6/6] Testing..."

# Test Python imports
python3 -c "import sounddevice, numpy; print('         Python imports OK')" 2>/dev/null || {
    echo "         ERROR: Python imports failed. Try: pip3 install sounddevice numpy scipy"
    exit 1
}

# Test audio devices
echo ""
echo "  Available audio input devices:"
python3 -c "
import sounddevice as sd
devices = sd.query_devices()
found_rode = False
for i, d in enumerate(devices):
    if d['max_input_channels'] > 0:
        name = d['name']
        marker = ''
        if 'rode' in name.lower() or 'virtual input' in name.lower():
            marker = ' <-- RODE'
            found_rode = True
        print(f'    [{i}] {name}{marker}')
if not found_rode:
    print()
    print('    WARNING: No se encontro el microfono RODE.')
    print('    Asegurate de que Rode Connect este abierto.')
"

# Test overlay notification
echo ""
echo "  Testing notification overlay..."
python3 -c "
import tkinter as tk
import threading
import platform

IS_MAC = platform.system() == 'Darwin'
FONT = 'SF Pro Display' if IS_MAC else 'Segoe UI'

def show():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.attributes('-alpha', 0.95)
    w, h = 380, 100
    screen_w = root.winfo_screenwidth()
    root.geometry(f'{w}x{h}+{screen_w - w - 20}+40')
    canvas = tk.Canvas(root, width=w, height=h, bg='#34C759', highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    canvas.create_rectangle(0, 0, 6, h, fill='#5EDC82', outline='')
    canvas.create_text(30, h//2-8, text='\u2713', fill='white', font=(FONT, 20), anchor='w')
    canvas.create_text(65, h//2-18, text='Setup Complete!', fill='white', font=(FONT, 13), anchor='w')
    canvas.create_text(65, h//2+10, text='Audio Monitor is ready to use.', fill='#D0F5DC', font=(FONT, 10), anchor='w')
    root.after(4000, root.destroy)
    root.mainloop()

show()
"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║          SETUP COMPLETE!              ║"
echo "  ╠══════════════════════════════════════╣"
echo "  ║  Para usar:                           ║"
echo "  ║  1. Abre Rode Connect                 ║"
echo "  ║  2. Doble clic en start-monitor       ║"
echo "  ║  3. Graba en OBS como siempre         ║"
echo "  ║  4. Si hay problema → alerta aparece  ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
