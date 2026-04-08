"""
Test the audio monitor detection against a file.
Simulates real-time playback — processes the audio in blocks just like the live monitor.
Usage: python test_file.py <audio_or_video_file>
"""

import sys
import os
import subprocess
import tempfile
import collections
import numpy as np
from scipy.io import wavfile
import config as cfg


def extract_audio(input_path):
    """Extract audio from any media file to a temp WAV."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    subprocess.run([
        "ffmpeg", "-i", input_path, "-vn",
        "-acodec", "pcm_s16le", "-ar", str(cfg.SAMPLE_RATE), "-ac", "1",
        tmp.name, "-y"
    ], capture_output=True)
    return tmp.name


def analyze(audio_path):
    sr, audio = wavfile.read(audio_path)
    audio = audio.astype(np.float32) / 32768.0
    duration = len(audio) / sr

    print(f"\n  File: {sys.argv[1]}")
    print(f"  Duration: {duration:.1f}s | Sample rate: {sr} Hz")
    print(f"  Processing in {cfg.BLOCK_SIZE}-sample blocks (~{cfg.BLOCK_SIZE/sr*1000:.0f}ms each)...")
    print()

    # Detection state
    silence_counter = 0
    silence_blocks_needed = int(cfg.SILENCE_DURATION_SEC * sr / cfg.BLOCK_SIZE)
    dead_signal_counter = 0
    dead_signal_blocks_needed = int(cfg.DEAD_SIGNAL_DURATION_SEC * sr / cfg.BLOCK_SIZE)
    clip_counter = 0
    clip_blocks_needed = int(cfg.CLIP_DURATION_SEC * sr / cfg.BLOCK_SIZE)
    pop_times = []
    alerts = []

    # Corruption detection state (spectral kurtosis)
    kurt_window_size = int(cfg.CORRUPTION_WINDOW_SEC * sr / cfg.CORRUPTION_BLOCK_SIZE)
    kurt_buffer = collections.deque(maxlen=kurt_window_size)
    kurt_confirm_count = int(cfg.CORRUPTION_CONFIRM_SEC * sr / cfg.CORRUPTION_BLOCK_SIZE)
    kurt_baseline_blocks = int(cfg.CORRUPTION_BASELINE_SEC * sr / cfg.CORRUPTION_BLOCK_SIZE)
    kurt_baseline_values = []
    kurt_baseline_ready = False
    corruption_counter = 0

    for i in range(0, len(audio), cfg.BLOCK_SIZE):
        chunk = audio[i:i + cfg.BLOCK_SIZE]
        if len(chunk) < cfg.BLOCK_SIZE:
            break

        t = i / sr
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        peak = float(np.abs(chunk).max())

        # Dead signal
        if rms < cfg.DEAD_SIGNAL_THRESHOLD:
            dead_signal_counter += 1
        else:
            dead_signal_counter = 0
        if dead_signal_counter == dead_signal_blocks_needed:
            alerts.append((t, "DEAD SIGNAL", "Signal is dead (absolute zero). USB disconnected?"))

        # Silence
        if rms < cfg.SILENCE_THRESHOLD_RMS:
            silence_counter += 1
        else:
            silence_counter = 0
        if silence_counter == silence_blocks_needed:
            alerts.append((t, "SILENCE", f"No voice for {cfg.SILENCE_DURATION_SEC:.0f}+ seconds"))

        # Pop/click
        diff = np.abs(np.diff(chunk))
        max_diff = float(diff.max())
        if max_diff > cfg.POP_DIFF_THRESHOLD and peak > cfg.POP_PEAK_THRESHOLD:
            pop_times.append(t)
            pop_times = [pt for pt in pop_times if t - pt < cfg.POP_CLUSTER_WINDOW_SEC]
            if len(pop_times) >= cfg.POP_CLUSTER_COUNT:
                alerts.append((t, "POP CLUSTER", f"Multiple pops detected (peak={peak:.2f}, diff={max_diff:.2f})"))
                pop_times.clear()

        # Clipping
        clip_ratio = float(np.mean(np.abs(chunk) > cfg.CLIP_THRESHOLD))
        if clip_ratio > cfg.CLIP_RATIO_THRESHOLD:
            clip_counter += 1
        else:
            clip_counter = max(0, clip_counter - 1)
        if clip_counter == clip_blocks_needed:
            alerts.append((t, "CLIPPING", f"Audio distortion ({clip_ratio*100:.0f}% samples clipping)"))

    # Corruption detection (spectral kurtosis) — uses larger blocks
    corruption_freqs = np.fft.rfftfreq(cfg.CORRUPTION_BLOCK_SIZE, 1.0 / sr)[1:]
    for i in range(0, len(audio) - cfg.CORRUPTION_BLOCK_SIZE, cfg.CORRUPTION_BLOCK_SIZE):
        block = audio[i:i + cfg.CORRUPTION_BLOCK_SIZE]
        t = i / sr
        block_rms = float(np.sqrt(np.mean(block ** 2)))
        if block_rms < cfg.CORRUPTION_MIN_RMS:
            continue

        fft = np.abs(np.fft.rfft(block))
        fft = fft[1:] + 1e-10
        freqs = corruption_freqs
        fft_norm = fft / np.sum(fft)
        mean_f = float(np.sum(freqs * fft_norm))
        var_f = float(np.sum(((freqs - mean_f) ** 2) * fft_norm))
        kurt = float(np.sum(((freqs - mean_f) ** 4) * fft_norm) / (var_f ** 2 + 1e-10))

        if not kurt_baseline_ready:
            kurt_baseline_values.append(kurt)
            if len(kurt_baseline_values) >= kurt_baseline_blocks:
                kurt_baseline_ready = True
                print(f"  Baseline kurtosis: median={np.median(kurt_baseline_values):.1f} (from first {cfg.CORRUPTION_BASELINE_SEC:.0f}s)")
            continue

        kurt_buffer.append(kurt)

        if len(kurt_buffer) >= kurt_window_size // 2:
            bad_ratio = sum(1 for k in kurt_buffer
                            if k < cfg.CORRUPTION_KURT_THRESHOLD) / len(kurt_buffer)
            if bad_ratio >= cfg.CORRUPTION_BAD_RATIO:
                corruption_counter += 1
            else:
                corruption_counter = max(0, corruption_counter - 1)

            if corruption_counter == kurt_confirm_count:
                median_kurt = float(np.median(list(kurt_buffer)))
                alerts.append((t, "CORRUPTION", f"Static/robotic audio (quality={median_kurt:.1f}, normal>10)"))
                corruption_counter = 0

    # Results
    if alerts:
        print(f"  === {len(alerts)} ALERT(S) DETECTED ===")
        print()
        for t, alert_type, msg in alerts:
            mins = int(t // 60)
            secs = t % 60
            print(f"  [{mins:02d}:{secs:05.2f}] {alert_type}: {msg}")
    else:
        print("  === NO ALERTS ===")
        print("  The file passed clean — no issues detected.")

    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("  Usage: python test_file.py <audio_or_video_file>")
        sys.exit(1)

    input_file = sys.argv[1]
    if not os.path.exists(input_file):
        print(f"  File not found: {input_file}")
        sys.exit(1)

    ext = os.path.splitext(input_file)[1].lower()
    supported = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".wav", ".flac", ".mp3", ".ogg")
    if ext not in supported:
        print(f"  Unsupported file type: {ext}")
        sys.exit(1)

    print(f"  Extracting audio...")
    wav_path = extract_audio(input_file)
    analyze(wav_path)
    os.remove(wav_path)
