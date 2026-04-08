"""
Demo mode: plays a video/audio file through the monitor in real-time.
Shows overlays exactly when corruption is detected — perfect for demos.
Usage: python demo_file.py <video_or_audio_file>
"""

import sys
import os
import platform
import time
import subprocess
import threading
import collections
import numpy as np
import tkinter as tk
import config as cfg

IS_MAC = platform.system() == "Darwin"
FONT_REGULAR = "SF Pro Display" if IS_MAC else "Segoe UI"
FONT_BOLD = "SF Pro Display Bold" if IS_MAC else "Segoe UI Semibold"
FONT_SMALL = "SF Pro Display" if IS_MAC else "Segoe UI"

# ─── Overlay + Sound (reused from monitor.py) ────────────────────────────────

def show_overlay(title, message, alert_type="warning"):
    def _show():
        colors = {
            "warning":  {"bg": "#FF3B30", "accent": "#FF6961", "text2": "#FFE0E0"},
            "caution":  {"bg": "#FF9500", "accent": "#FFB340", "text2": "#FFF0D0"},
            "info":     {"bg": "#007AFF", "accent": "#4DA3FF", "text2": "#D0E8FF"},
            "success":  {"bg": "#34C759", "accent": "#5EDC82", "text2": "#D0F5DC"},
        }
        c = colors.get(alert_type, colors["warning"])
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.95)
        w, h = cfg.OVERLAY_WIDTH, cfg.OVERLAY_HEIGHT
        screen_w = root.winfo_screenwidth()
        x = screen_w - w - 20
        y = 40
        root.geometry(f"{w}x{h}+{x}+{y}")
        canvas = tk.Canvas(root, width=w, height=h, bg=c["bg"], highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_rectangle(0, 0, 6, h, fill=c["accent"], outline="")
        icons = {"warning": "\u26a0", "caution": "\u26a1", "info": "\u2139", "success": "\u2713"}
        canvas.create_text(30, h // 2 - 8, text=icons.get(alert_type, "\u26a0"),
                           fill="white", font=(FONT_REGULAR, 20), anchor="w")
        canvas.create_text(65, h // 2 - 18, text=title, fill="white",
                           font=(FONT_BOLD, 13), anchor="w")
        canvas.create_text(65, h // 2 + 10, text=message, fill=c["text2"],
                           font=(FONT_REGULAR, 10), anchor="w")
        canvas.create_text(w - 15, 12, text="AUDIO MONITOR", fill=c["text2"],
                           font=(FONT_SMALL, 7), anchor="e")
        root.after(cfg.OVERLAY_DURATION_MS, root.destroy)
        root.mainloop()
    threading.Thread(target=_show, daemon=True).start()


def play_alert_sound(repeats=1):
    try:
        import sounddevice as sd
        t = np.linspace(0, cfg.ALERT_DURATION_SEC,
                        int(cfg.SAMPLE_RATE * cfg.ALERT_DURATION_SEC), False)
        tone = np.sin(2 * np.pi * cfg.ALERT_FREQ_HZ * t) * 0.5
        fade = min(500, len(tone) // 4)
        tone[:fade] *= np.linspace(0, 1, fade)
        tone[-fade:] *= np.linspace(1, 0, fade)
        for i in range(repeats):
            sd.play(tone.astype(np.float32), cfg.SAMPLE_RATE)
            sd.wait()
            if i < repeats - 1:
                time.sleep(0.1)
    except Exception:
        pass


# ─── Alert Dispatch ──────────────────────────────────────────────────────────

last_alert_times = {}

def dispatch_alert(alert_type, detail, elapsed):
    now = time.time()
    cooldown = cfg.COOLDOWN.get(alert_type, 15)
    if now - last_alert_times.get(alert_type, 0) < cooldown:
        return
    last_alert_times[alert_type] = now

    messages = {
        "corruption": ("Audio Corrupted!",
                        f"Static/robotic audio detected ({detail})",
                        "warning", cfg.ALERT_REPEAT),
        "pop": ("Audio Pop Detected",
                 f"Cable bump or USB glitch ({detail})",
                 "warning", cfg.ALERT_REPEAT),
        "clipping": ("Audio Clipping",
                      "Signal is distorting",
                      "warning", 2),
    }
    title, msg, style, beeps = messages.get(alert_type, ("Alert", detail, "warning", 1))

    mins = int(elapsed // 60)
    secs = elapsed % 60
    print(f"\n  [{mins:02d}:{secs:05.2f}] !!! {title}: {msg}")

    show_overlay(title, msg, style)
    threading.Thread(target=play_alert_sound, args=(beeps,), daemon=True).start()


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("  Usage: python demo_file.py <video_or_audio_file>")
        sys.exit(1)

    input_file = sys.argv[1]
    if not os.path.exists(input_file):
        print(f"  File not found: {input_file}")
        sys.exit(1)

    SR = cfg.SAMPLE_RATE
    BLOCK = cfg.CORRUPTION_BLOCK_SIZE  # 4096 samples

    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║    AUDIO MONITOR v1.0 (FILE DEMO)    ║")
    print("  ╚══════════════════════════════════════╝")
    print()
    print(f"  File: {os.path.basename(input_file)}")
    print(f"  Playing in real-time with detection...")
    print()

    show_overlay("Demo Started", f"Playing: {os.path.basename(input_file)}", "info")

    # Launch ffmpeg to stream raw PCM at real-time speed
    proc = subprocess.Popen([
        "ffmpeg", "-re",  # -re = real-time playback speed
        "-i", input_file,
        "-vn",  # no video
        "-acodec", "pcm_f32le",  # 32-bit float
        "-ar", str(SR),
        "-ac", "1",  # mono
        "-f", "f32le",  # raw format
        "pipe:1"  # output to stdout
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    # Detection state
    kurt_buffer = collections.deque(maxlen=int(cfg.CORRUPTION_WINDOW_SEC * SR / BLOCK))
    kurt_confirm_count = int(cfg.CORRUPTION_CONFIRM_SEC * SR / BLOCK)
    kurt_baseline_blocks = int(cfg.CORRUPTION_BASELINE_SEC * SR / BLOCK)
    kurt_baseline_values = []
    kurt_baseline_ready = False
    corruption_counter = 0
    pop_times = []
    freqs = np.fft.rfftfreq(BLOCK, 1.0 / SR)[1:]

    bytes_per_block = BLOCK * 4  # float32 = 4 bytes
    samples_read = 0

    try:
        while True:
            raw = proc.stdout.read(bytes_per_block)
            if len(raw) < bytes_per_block:
                break

            block = np.frombuffer(raw, dtype=np.float32)
            samples_read += BLOCK
            elapsed = samples_read / SR

            rms = float(np.sqrt(np.mean(block ** 2)))
            peak = float(np.abs(block).max())

            # Level meter
            if rms <= 0:
                db = -96.0
            else:
                db = max(-96.0, 20 * np.log10(rms))
            bar_len = 40
            level = max(0, min(bar_len, int((db + 60) / 60 * bar_len)))
            bar = "\u2588" * level + "\u2591" * (bar_len - level)
            mins = int(elapsed // 60)
            secs = elapsed % 60
            sys.stdout.write(f"\r  [{mins:02d}:{secs:04.1f}] {bar} {db:5.1f} dB   ")
            sys.stdout.flush()

            if rms < cfg.CORRUPTION_MIN_RMS:
                continue

            # Pop detection
            diff = np.abs(np.diff(block))
            max_diff = float(diff.max())
            if max_diff > cfg.POP_DIFF_THRESHOLD and peak > cfg.POP_PEAK_THRESHOLD:
                pop_times.append(elapsed)
                pop_times = [t for t in pop_times if elapsed - t < cfg.POP_CLUSTER_WINDOW_SEC]
                if len(pop_times) >= cfg.POP_CLUSTER_COUNT:
                    dispatch_alert("pop", f"peak={peak:.2f}", elapsed)
                    pop_times.clear()

            # Corruption detection (spectral kurtosis)
            fft = np.abs(np.fft.rfft(block))
            fft = fft[1:] + 1e-10
            fft_norm = fft / np.sum(fft)
            mean_f = float(np.sum(freqs * fft_norm))
            var_f = float(np.sum(((freqs - mean_f) ** 2) * fft_norm))
            kurt = float(np.sum(((freqs - mean_f) ** 4) * fft_norm) / (var_f ** 2 + 1e-10))

            if not kurt_baseline_ready:
                kurt_baseline_values.append(kurt)
                if len(kurt_baseline_values) >= kurt_baseline_blocks:
                    kurt_baseline_ready = True
                    median = np.median(kurt_baseline_values)
                    print(f"\n  Baseline kurtosis: {median:.1f} (from first {cfg.CORRUPTION_BASELINE_SEC:.0f}s)")
                continue

            kurt_buffer.append(kurt)
            if len(kurt_buffer) >= kurt_buffer.maxlen // 2:
                bad_ratio = sum(1 for k in kurt_buffer
                                if k < cfg.CORRUPTION_KURT_THRESHOLD) / len(kurt_buffer)
                if bad_ratio >= cfg.CORRUPTION_BAD_RATIO:
                    corruption_counter += 1
                else:
                    corruption_counter = max(0, corruption_counter - 1)

                if corruption_counter >= kurt_confirm_count:
                    median_kurt = float(np.median(list(kurt_buffer)))
                    dispatch_alert("corruption", f"quality={median_kurt:.1f}", elapsed)
                    corruption_counter = 0

    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        print("\n\n  Demo finished.")
        show_overlay("Demo Complete", "File playback ended", "success")
        time.sleep(3)


if __name__ == "__main__":
    main()
