"""
Audio Monitor for Rode NT USB+ via Rode Connect
Monitors the processed audio signal in real-time and alerts on issues.
"""

import sys
import platform
import time
import queue
import threading
import collections
import numpy as np
import sounddevice as sd
import tkinter as tk
import config as cfg

# Cross-platform font detection
IS_MAC = platform.system() == "Darwin"
FONT_REGULAR = "SF Pro Display" if IS_MAC else "Segoe UI"
FONT_BOLD = "SF Pro Display Bold" if IS_MAC else "Segoe UI Semibold"
FONT_SMALL = "SF Pro Display" if IS_MAC else "Segoe UI"


# ─── Alert Queue (callback thread → main thread) ────────────────────────────

alert_queue = queue.Queue()


# ─── Detection State ─────────────────────────────────────────────────────────

class DetectionState:
    def __init__(self):
        self.silence_counter = 0
        self.silence_blocks_needed = int(cfg.SILENCE_DURATION_SEC * cfg.SAMPLE_RATE / cfg.BLOCK_SIZE)
        self.dead_signal_counter = 0
        self.dead_signal_blocks_needed = int(cfg.DEAD_SIGNAL_DURATION_SEC * cfg.SAMPLE_RATE / cfg.BLOCK_SIZE)
        self.clip_counter = 0
        self.clip_blocks_needed = int(cfg.CLIP_DURATION_SEC * cfg.SAMPLE_RATE / cfg.BLOCK_SIZE)
        self.pop_times = []  # timestamps of recent pops
        self.last_callback_time = time.time()
        self.callback_count = 0
        self.last_rms = 0.0
        self.last_peak = 0.0
        # Corruption detection (spectral kurtosis)
        self.kurt_window_size = int(cfg.CORRUPTION_WINDOW_SEC * cfg.SAMPLE_RATE / cfg.CORRUPTION_BLOCK_SIZE)
        self.kurt_buffer = collections.deque(maxlen=self.kurt_window_size)
        self.kurt_confirm_count = int(cfg.CORRUPTION_CONFIRM_SEC * cfg.SAMPLE_RATE / cfg.CORRUPTION_BLOCK_SIZE)
        self.kurt_baseline_blocks = int(cfg.CORRUPTION_BASELINE_SEC * cfg.SAMPLE_RATE / cfg.CORRUPTION_BLOCK_SIZE)
        self.kurt_baseline_values = []
        self.kurt_baseline_ready = False
        self.corruption_counter = 0
        # Accumulator for building larger blocks from the stream's smaller blocks
        self.corruption_accumulator = collections.deque()
        # Precomputed FFT frequencies (block size is constant)
        self.corruption_freqs = np.fft.rfftfreq(cfg.CORRUPTION_BLOCK_SIZE, 1.0 / cfg.SAMPLE_RATE)[1:]

state = DetectionState()


# ─── Audio Callback ──────────────────────────────────────────────────────────

def audio_callback(indata, frames, time_info, status):
    """Called ~23 times/second with audio data from the stream."""
    state.last_callback_time = time.time()
    state.callback_count += 1

    # Skip first 10 blocks (grace period — initial buffer may have garbage)
    if state.callback_count <= 10:
        return

    # Handle stream errors (USB issues)
    if status:
        error_msg = str(status)
        alert_queue.put_nowait(("usb_error", f"Stream error: {error_msg}"))
        return

    audio = indata[:, 0]  # Use first channel
    rms = float(np.sqrt(np.mean(audio ** 2)))
    peak = float(np.abs(audio).max())
    state.last_rms = rms
    state.last_peak = peak

    # ── Dead Signal Detection (USB cable pulled — absolute zero) ──
    if rms < cfg.DEAD_SIGNAL_THRESHOLD:
        state.dead_signal_counter += 1
    else:
        state.dead_signal_counter = 0

    if state.dead_signal_counter >= state.dead_signal_blocks_needed:
        alert_queue.put_nowait(("dead_signal", "Signal is dead (0). Cable disconnected?"))
        state.dead_signal_counter = 0

    # ── Silence / Dropout Detection (nobody talking) ──
    if rms < cfg.SILENCE_THRESHOLD_RMS:
        state.silence_counter += 1
    else:
        state.silence_counter = 0

    if state.silence_counter >= state.silence_blocks_needed:
        alert_queue.put_nowait(("silence", f"No voice for {cfg.SILENCE_DURATION_SEC:.0f}+ seconds"))
        state.silence_counter = 0

    # ── Pop / Click Detection ──
    diff = np.abs(np.diff(audio))
    max_diff = float(diff.max())

    if max_diff > cfg.POP_DIFF_THRESHOLD and peak > cfg.POP_PEAK_THRESHOLD:
        now = time.time()
        state.pop_times.append(now)
        # Clean old pops outside the cluster window
        state.pop_times = [t for t in state.pop_times
                           if now - t < cfg.POP_CLUSTER_WINDOW_SEC]
        if len(state.pop_times) >= cfg.POP_CLUSTER_COUNT:
            alert_queue.put_nowait(("pop", f"Pop cluster detected (peak={peak:.2f})"))
            state.pop_times.clear()

    # ── Clipping / Distortion Detection ──
    clip_ratio = float(np.mean(np.abs(audio) > cfg.CLIP_THRESHOLD))
    if clip_ratio > cfg.CLIP_RATIO_THRESHOLD:
        state.clip_counter += 1
    else:
        state.clip_counter = max(0, state.clip_counter - 1)

    if state.clip_counter >= state.clip_blocks_needed:
        alert_queue.put_nowait(("clipping", f"Audio clipping ({clip_ratio*100:.0f}% samples)"))
        state.clip_counter = 0

    # ── Audio Corruption Detection (spectral kurtosis) ──
    # Accumulate samples into larger blocks for better frequency resolution
    state.corruption_accumulator.extend(audio)
    while len(state.corruption_accumulator) >= cfg.CORRUPTION_BLOCK_SIZE:
        block = np.array([state.corruption_accumulator.popleft()
                          for _ in range(cfg.CORRUPTION_BLOCK_SIZE)], dtype=np.float32)

        block_rms = float(np.sqrt(np.mean(block ** 2)))
        if block_rms < cfg.CORRUPTION_MIN_RMS:
            continue  # Skip room noise — kurtosis is meaningless without speech

        # Compute spectral kurtosis
        fft = np.abs(np.fft.rfft(block))
        fft = fft[1:] + 1e-10
        freqs = state.corruption_freqs
        fft_norm = fft / np.sum(fft)
        mean_f = float(np.sum(freqs * fft_norm))
        var_f = float(np.sum(((freqs - mean_f) ** 2) * fft_norm))
        kurt = float(np.sum(((freqs - mean_f) ** 4) * fft_norm) / (var_f ** 2 + 1e-10))

        if not state.kurt_baseline_ready:
            state.kurt_baseline_values.append(kurt)
            if len(state.kurt_baseline_values) >= state.kurt_baseline_blocks:
                state.kurt_baseline_ready = True
            continue

        # Rolling buffer (deque auto-drops old values)
        state.kurt_buffer.append(kurt)

        # Check percentage of bad blocks in rolling window
        if len(state.kurt_buffer) >= state.kurt_window_size // 2:
            bad_ratio = sum(1 for k in state.kurt_buffer
                            if k < cfg.CORRUPTION_KURT_THRESHOLD) / len(state.kurt_buffer)
            if bad_ratio >= cfg.CORRUPTION_BAD_RATIO:
                state.corruption_counter += 1
            else:
                state.corruption_counter = max(0, state.corruption_counter - 1)

            if state.corruption_counter >= state.kurt_confirm_count:
                median_kurt = float(np.median(state.kurt_buffer))
                alert_queue.put_nowait(("corruption",
                    f"Static/robotic audio detected (quality={median_kurt:.1f}, normal>10)"))
                state.corruption_counter = 0


# ─── Overlay Notification ────────────────────────────────────────────────────

def show_overlay(title, message, alert_type="warning"):
    """Show a custom overlay notification (runs in its own thread)."""
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

        # Left accent bar
        canvas.create_rectangle(0, 0, 6, h, fill=c["accent"], outline="")

        # Icon
        icons = {"warning": "\u26a0", "caution": "\u26a1", "info": "\u2139", "success": "\u2713"}
        icon = icons.get(alert_type, "\u26a0")
        canvas.create_text(30, h // 2 - 8, text=icon, fill="white",
                           font=(FONT_REGULAR, 20), anchor="w")

        # Text
        canvas.create_text(65, h // 2 - 18, text=title, fill="white",
                           font=(FONT_BOLD, 13), anchor="w")
        canvas.create_text(65, h // 2 + 10, text=message, fill=c["text2"],
                           font=(FONT_REGULAR, 10), anchor="w")

        # App name
        canvas.create_text(w - 15, 12, text="AUDIO MONITOR", fill=c["text2"],
                           font=(FONT_SMALL, 7), anchor="e")

        root.after(cfg.OVERLAY_DURATION_MS, root.destroy)
        root.mainloop()

    thread = threading.Thread(target=_show, daemon=True)
    thread.start()


# ─── Alert Sound ─────────────────────────────────────────────────────────────

def play_alert_sound(repeats=1):
    """Play a short beep through the default output device."""
    try:
        t = np.linspace(0, cfg.ALERT_DURATION_SEC, int(cfg.SAMPLE_RATE * cfg.ALERT_DURATION_SEC), False)
        # Sine wave with fade in/out to avoid clicks
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
        pass  # Don't crash if sound fails


# ─── Alert Dispatch ──────────────────────────────────────────────────────────

last_alert_times = {}

def dispatch_alert(alert_type, detail):
    """Send overlay + sound, respecting cooldowns."""
    now = time.time()
    cooldown = cfg.COOLDOWN.get(alert_type, 15)
    if now - last_alert_times.get(alert_type, 0) < cooldown:
        return
    last_alert_times[alert_type] = now

    messages = {
        "dead_signal": ("Signal Lost!",
                         "USB cable disconnected or mic off. Check immediately!",
                         "warning", cfg.ALERT_REPEAT),
        "corruption": ("Audio Corrupted!",
                        "Static/robotic audio detected. Check USB cable!",
                        "warning", cfg.ALERT_REPEAT),
        "silence": ("Silence Detected",
                     f"No voice for {cfg.SILENCE_DURATION_SEC/60:.0f}+ min. Check mic!",
                     "caution", 2),
        "pop": ("Audio Pop Detected",
                 "Cable bump or USB glitch detected.",
                 "warning", cfg.ALERT_REPEAT),
        "clipping": ("Audio Clipping",
                      "Signal is distorting. Check gain or move back.",
                      "warning", 2),
        "usb_error": ("USB Stream Error",
                       detail,
                       "warning", cfg.ALERT_REPEAT),
        "disconnect": ("Mic Disconnected",
                        "Rode NT-USB+ lost. Attempting reconnect...",
                        "warning", cfg.ALERT_REPEAT),
        "reconnect": ("Mic Reconnected",
                       "Monitoring resumed.",
                       "success", 1),
    }

    title, msg, style, beeps = messages.get(alert_type, ("Alert", detail, "warning", 1))

    timestamp = time.strftime("%H:%M:%S")
    print(f"\n  [{timestamp}] !!! {title}: {msg}")

    show_overlay(title, msg, style)
    threading.Thread(target=play_alert_sound, args=(beeps,), daemon=True).start()


# ─── Device Discovery ────────────────────────────────────────────────────────

def find_device():
    """Find the Rode Connect virtual device, preferring shared-access APIs."""
    devices = sd.query_devices()
    host_apis = sd.query_hostapis()

    # On Windows, prefer shared-access APIs (MME, DirectSound) so OBS can use the device too
    if not IS_MAC:
        preferred_apis = ["mme", "directsound"]
        for name_search in [cfg.DEVICE_NAME, cfg.DEVICE_FALLBACK]:
            for i, d in enumerate(devices):
                if name_search.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                    api_name = host_apis[d["hostapi"]]["name"].lower()
                    if any(p in api_name for p in preferred_apis):
                        return i, d

    # Any API (Mac uses CoreAudio which always allows shared access)
    for name_search in [cfg.DEVICE_NAME, cfg.DEVICE_FALLBACK]:
        for i, d in enumerate(devices):
            if name_search.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                return i, d

    # Also try "Virtual Input" as a fallback (Rode Connect on some systems)
    for i, d in enumerate(devices):
        if "virtual input" in d["name"].lower() and d["max_input_channels"] > 0:
            return i, d

    return None, None


# ─── Level Meter ─────────────────────────────────────────────────────────────

def rms_to_db(rms):
    if rms <= 0:
        return -96.0
    return max(-96.0, 20 * np.log10(rms))


def print_level_meter():
    """Print an updating level meter to the console."""
    rms = state.last_rms
    peak = state.last_peak
    db = rms_to_db(rms)

    bar_len = 40
    level = max(0, min(bar_len, int((db + 60) / 60 * bar_len)))  # -60dB to 0dB range
    bar = "\u2588" * level + "\u2591" * (bar_len - level)

    status = "OK"
    if rms < cfg.SILENCE_THRESHOLD_RMS:
        status = "SILENT"
    elif peak > cfg.POP_PEAK_THRESHOLD:
        status = "HIGH"

    sys.stdout.write(f"\r  Levels: {bar} {db:5.1f} dB  ({status})   ")
    sys.stdout.flush()


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║         AUDIO MONITOR v1.0           ║")
    print("  ║   Rode NT-USB+ via Rode Connect      ║")
    print("  ╚══════════════════════════════════════╝")
    print()

    # Find device
    device_idx, device_info = find_device()
    if device_idx is None:
        print("  ERROR: No se encontro el microfono / Mic not found.")
        print("  Abre Rode Connect primero / Open Rode Connect first.")
        print()
        input_devices = [(i, d) for i, d in enumerate(sd.query_devices())
                         if d["max_input_channels"] > 0]
        if input_devices:
            print("  Dispositivos disponibles / Available devices:")
            for i, d in input_devices:
                print(f"    [{i}] {d['name']}")
            print()
            try:
                choice = input("  Selecciona el numero del dispositivo / Pick device number: ").strip()
                if choice.isdigit():
                    idx = int(choice)
                    device_idx = idx
                    device_info = sd.query_devices(idx)
                else:
                    return
            except (EOFError, KeyboardInterrupt):
                return
        else:
            print("  No hay dispositivos de audio disponibles.")
            input("  Press Enter to exit...")
            return

    device_name = device_info["name"]
    sample_rate = int(device_info["default_samplerate"])
    channels = min(cfg.CHANNELS, device_info["max_input_channels"])

    print(f"  Device: {device_name}")
    print(f"  Sample rate: {sample_rate} Hz | Channels: {channels}")
    print(f"  Block size: {cfg.BLOCK_SIZE} (~{cfg.BLOCK_SIZE/sample_rate*1000:.0f}ms)")
    print()
    print(f"  Silence alert: {cfg.SILENCE_DURATION_SEC:.0f}s | Pop threshold: {cfg.POP_DIFF_THRESHOLD}")
    print(f"  Press Ctrl+C to stop.")
    print()

    # Show startup notification
    show_overlay("Monitoring Started", f"{device_name} @ {sample_rate}Hz", "info")

    # Open audio stream
    stream = None
    try:
        stream = sd.InputStream(
            device=device_idx,
            samplerate=sample_rate,
            blocksize=cfg.BLOCK_SIZE,
            channels=channels,
            dtype="float32",
            callback=audio_callback,
        )
        stream.start()

        # Main loop
        meter_interval = 0.2  # Update meter 5x per second
        last_meter = 0

        while True:
            # Process alerts from callback thread
            try:
                alert_type, detail = alert_queue.get(timeout=0.05)
                dispatch_alert(alert_type, detail)
            except queue.Empty:
                pass

            # Watchdog: detect USB disconnect
            if state.callback_count > 10:  # Only after grace period
                elapsed = time.time() - state.last_callback_time
                if elapsed > cfg.DISCONNECT_TIMEOUT_SEC:
                    dispatch_alert("disconnect", "")
                    # Attempt reconnect
                    stream.stop()
                    stream.close()
                    print("\n  Attempting to reconnect...")
                    reconnected = False
                    for attempt in range(cfg.RECONNECT_MAX_ATTEMPTS):
                        time.sleep(cfg.RECONNECT_INTERVAL_SEC)
                        print(f"  Reconnect attempt {attempt + 1}/{cfg.RECONNECT_MAX_ATTEMPTS}...")
                        new_idx, new_info = find_device()
                        if new_idx is not None:
                            try:
                                stream = sd.InputStream(
                                    device=new_idx,
                                    samplerate=int(new_info["default_samplerate"]),
                                    blocksize=cfg.BLOCK_SIZE,
                                    channels=min(cfg.CHANNELS, new_info["max_input_channels"]),
                                    dtype="float32",
                                    callback=audio_callback,
                                )
                                stream.start()
                                state.last_callback_time = time.time()
                                state.callback_count = 0
                                dispatch_alert("reconnect", "")
                                print(f"  Reconnected to: {new_info['name']}")
                                reconnected = True
                                break
                            except Exception:
                                continue
                    if not reconnected:
                        print("\n  Could not reconnect. Exiting.")
                        show_overlay("Monitor Stopped", "Could not reconnect to mic.", "warning")
                        time.sleep(5)
                        return

            # Update level meter
            now = time.time()
            if now - last_meter > meter_interval:
                print_level_meter()
                last_meter = now

    except KeyboardInterrupt:
        print("\n\n  Monitor stopped by user.")
    except Exception as e:
        print(f"\n  ERROR: {e}")
    finally:
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
