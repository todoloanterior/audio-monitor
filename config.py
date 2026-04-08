"""
Audio Monitor Configuration
Thresholds calibrated from Felipe's real glitch sample (gltich.mp4).
Adjust these values if you get too many false alarms or miss real issues.
"""

# === DEVICE ===
# Substring to find the correct audio device.
# On Windows: "RØDE Connect Virtual In" (the processed output from Rode Connect)
# On Mac: will likely be similar — run monitor.py to list devices if not found.
DEVICE_NAME = "RØDE Connect"

# Fallback: try raw mic if virtual device not found
DEVICE_FALLBACK = "RØDE NT-USB"

# === AUDIO STREAM ===
SAMPLE_RATE = 48000
BLOCK_SIZE = 2048       # ~42ms per block at 48kHz
CHANNELS = 2            # Rode Connect Virtual outputs stereo

# === SILENCE / DROPOUT DETECTION ===
# Room noise with mic on (nobody talking) is ~0.001 RMS (-60dB).
# Normal speech RMS is 0.01-0.13.
# This is a SAFETY NET — only fires after 3 minutes of silence.
# Dead signal (2s) and corruption (~2.5s) catch issues faster.
# 3 minutes = no normal pause lasts this long during a recording session.
SILENCE_THRESHOLD_RMS = 0.003    # Below this = nobody talking (room noise is ~0.001)
SILENCE_DURATION_SEC = 180.0     # 3 minutes — safety net only, not for normal pauses

# === AUDIO CORRUPTION DETECTION (static/robotic glitch) ===
# Calibrated from Felipe's real glitch files (gltich.mp4, glitched v2.mp4).
# Corruption = audio sounds robotic/static but signal levels look normal.
# Detection: spectral kurtosis — clean speech has peaky harmonics (kurt ~14-18),
# corrupted audio has flat/noisy spectrum (kurt ~5-7).
# Uses a rolling window of median kurtosis values.
CORRUPTION_BLOCK_SIZE = 4096          # Larger block for better frequency resolution (~85ms)
CORRUPTION_MIN_RMS = 0.01            # Only analyze blocks with actual speech (skip room noise)
CORRUPTION_BASELINE_SEC = 10.0        # Seconds to build "clean" kurtosis baseline
CORRUPTION_KURT_THRESHOLD = 8.0       # Kurtosis below this = suspect block
CORRUPTION_WINDOW_SEC = 3.0           # Rolling window size
CORRUPTION_BAD_RATIO = 0.70           # 70%+ of blocks in window must be below threshold
CORRUPTION_CONFIRM_SEC = 2.0          # Must stay bad for 2s to alert

# === POP / CLICK DETECTION ===
# Note: Rode Connect smooths out cable bumps, so pops may not pass through.
# Kept as fallback for raw mic monitoring.
POP_DIFF_THRESHOLD = 0.30        # Max sample-to-sample jump
POP_PEAK_THRESHOLD = 0.60        # Block must also have high peak (avoids false positives)
POP_CLUSTER_COUNT = 3            # Number of pops within the window to trigger alert
POP_CLUSTER_WINDOW_SEC = 1.0     # Window to count pop clusters

# === CLIPPING / DISTORTION DETECTION ===
CLIP_THRESHOLD = 0.95            # Sample amplitude considered clipping
CLIP_RATIO_THRESHOLD = 0.05      # 5% of samples in a block must be clipping
CLIP_DURATION_SEC = 0.5          # Must persist for this long

# === DEAD SIGNAL DETECTION (USB disconnect / cable pulled) ===
# When USB cable is unplugged, Rode Connect virtual device keeps running but sends
# absolute zeros (-96 dB). This is different from room silence (~-60 dB).
DEAD_SIGNAL_THRESHOLD = 0.00005  # Below this = absolute zero (dead USB)
DEAD_SIGNAL_DURATION_SEC = 2.0   # Alert after 2 seconds of dead signal (fast!)

# === USB DISCONNECT DETECTION (stream stops) ===
DISCONNECT_TIMEOUT_SEC = 2.0     # If no callback for this long = disconnected

# === NOTIFICATION COOLDOWNS (seconds) ===
COOLDOWN = {
    "silence": 30,
    "dead_signal": 10,
    "corruption": 15,
    "pop": 15,
    "clipping": 20,
    "disconnect": 60,
    "reconnect": 5,
}

# === RECONNECT ===
RECONNECT_INTERVAL_SEC = 10
RECONNECT_MAX_ATTEMPTS = 6

# === ALERT SOUND ===
# Frequency and duration for the alert beep (played through default output)
ALERT_FREQ_HZ = 880         # A5 note
ALERT_DURATION_SEC = 0.3
ALERT_REPEAT = 3             # Number of beeps for critical alerts

# === OVERLAY APPEARANCE ===
OVERLAY_WIDTH = 380
OVERLAY_HEIGHT = 100
OVERLAY_DURATION_MS = 5000   # How long overlay stays on screen
