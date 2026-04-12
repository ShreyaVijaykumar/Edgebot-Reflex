"""
EdgeBot Reflex - Python AI Bridge
==================================
Dual-model robot AI: Falcon Mamba (fast reflex) + SmolVLA (planning)
with a live terminal dashboard showing LED states, sensor distance,
and model decisions in real time.

Run:  python edgebot_bridge.py
Stop: Ctrl+C
"""

import json
import threading
import time
import random
import os
import sys
from collections import deque
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────
DANGER_DIST_CM   = 15.0
CAUTION_DIST_CM  = 30.0
SMOLVLA_INTERVAL = 0.2
USE_REAL_MODELS  = False
GOAL_TEXT        = "navigate forward to the blue box, avoid obstacles"

# ── Shared state ──────────────────────────────────────────────────────────────
state_lock     = threading.Lock()
latest_dist_cm = 400.0
mamba_cmd      = "FWD"
smolvla_cmd    = "PLAN_FWD"
arbiter_cmd    = "FWD"
sensor_history = deque(maxlen=20)
log_lines      = []          # rolling log for dashboard
log_lock       = threading.Lock()

def add_log(line):
    with log_lock:
        log_lines.append(line)
        if len(log_lines) > 6:
            log_lines.pop(0)


# ══════════════════════════════════════════════════════════════════════════════
# FAKE SERIAL  — simulates ESP32 sensor stream
# ══════════════════════════════════════════════════════════════════════════════

class FakeSerial:
    def __init__(self):
        self._dist      = 80.0
        self._direction = -1
        self.in_waiting = 0
        self._buf       = b""
        self._last      = time.time()

    def read(self, n=1):
        now = time.time()
        if now - self._last > 0.05:
            self._last = now
            self._dist += self._direction * random.uniform(1, 4)
            if self._dist < 4:
                self._direction = 1
            elif self._dist > 120:
                self._direction = -1
            frame = json.dumps({
                "dist_cm": round(self._dist, 1),
                "ts": int(now * 1000)
            }) + "\n"
            self._buf += frame.encode()
        if self._buf:
            chunk = self._buf[:n]
            self._buf = self._buf[n:]
            return chunk
        return b""

    def write(self, data):
        pass


# ══════════════════════════════════════════════════════════════════════════════
# SERIAL READER
# ══════════════════════════════════════════════════════════════════════════════

def serial_reader_thread(ser):
    global latest_dist_cm
    buf = ""
    while True:
        try:
            chunk = ser.read(ser.in_waiting or 1)
            buf += chunk.decode(errors="ignore")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    frame = json.loads(line)
                    if "dist_cm" in frame:
                        with state_lock:
                            latest_dist_cm = float(frame["dist_cm"])
                            sensor_history.append(latest_dist_cm)
                except json.JSONDecodeError:
                    pass
        except Exception:
            time.sleep(0.1)


# ══════════════════════════════════════════════════════════════════════════════
# FALCON MAMBA — fast reflex (stub)
# ══════════════════════════════════════════════════════════════════════════════

def mamba_reflex_stub(history):
    if not history:
        return "FWD"
    dist = history[-1]
    if dist < DANGER_DIST_CM:
        return "STOP"
    if dist < CAUTION_DIST_CM:
        if len(history) >= 3 and history[-1] < history[-3]:
            return "LEFT" if random.random() > 0.5 else "RIGHT"
    return "FWD"


def mamba_thread(ser):
    global mamba_cmd
    while True:
        with state_lock:
            history = list(sensor_history)

        t0  = time.perf_counter()
        cmd = mamba_reflex_stub(history)
        ms  = (time.perf_counter() - t0) * 1000

        with state_lock:
            mamba_cmd = cmd

        _run_arbiter(ser)

        dist_str = f"{history[-1]:5.1f}" if history else "  ?.?"
        add_log(f"  Mamba  {datetime.now().strftime('%H:%M:%S')}  "
                f"dist={dist_str}cm  cmd={cmd:<8}  {ms:.2f}ms")
        time.sleep(0.05)


# ══════════════════════════════════════════════════════════════════════════════
# SMOLVLA — planning (stub)
# ══════════════════════════════════════════════════════════════════════════════

def smolvla_plan_stub(dist_cm):
    if dist_cm > CAUTION_DIST_CM:
        return "PLAN_FWD"
    elif dist_cm > DANGER_DIST_CM:
        return "PLAN_LEFT" if random.random() > 0.5 else "PLAN_RIGHT"
    return "PLAN_STOP"


def smolvla_thread(ser):
    global smolvla_cmd
    while True:
        time.sleep(SMOLVLA_INTERVAL)
        with state_lock:
            dist = latest_dist_cm

        t0  = time.perf_counter()
        cmd = smolvla_plan_stub(dist)
        ms  = (time.perf_counter() - t0) * 1000

        with state_lock:
            smolvla_cmd = cmd

        add_log(f"  SmolVLA {datetime.now().strftime('%H:%M:%S')}  "
                f"plan={cmd:<14}  {ms:.2f}ms")


# ══════════════════════════════════════════════════════════════════════════════
# PRIORITY ARBITER
# ══════════════════════════════════════════════════════════════════════════════

def _run_arbiter(ser):
    global arbiter_cmd
    with state_lock:
        dist  = latest_dist_cm
        m_cmd = mamba_cmd
        s_cmd = smolvla_cmd

    chosen = m_cmd if (m_cmd == "STOP" or dist < CAUTION_DIST_CM) else s_cmd

    with state_lock:
        arbiter_cmd = chosen

    try:
        ser.write((json.dumps({"cmd": chosen}) + "\n").encode())
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# TERMINAL DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def led_display(state):
    """Return a coloured LED block for terminal."""
    return "●" if state else "○"


def draw_dashboard():
    with state_lock:
        dist  = latest_dist_cm
        m_cmd = mamba_cmd
        s_cmd = smolvla_cmd
        a_cmd = arbiter_cmd

    # Determine LED states
    led_red   = (a_cmd == "STOP")
    led_green = (a_cmd in ("FWD", "LEFT", "RIGHT"))
    led_blue  = (a_cmd.startswith("PLAN_"))

    # Distance bar (0-120cm mapped to 40 chars)
    bar_len  = 40
    filled   = min(bar_len, int((dist / 120.0) * bar_len))
    bar      = "█" * filled + "░" * (bar_len - filled)

    # Zone label
    if dist < DANGER_DIST_CM:
        zone = "DANGER  "
    elif dist < CAUTION_DIST_CM:
        zone = "CAUTION "
    else:
        zone = "SAFE    "

    # Clear screen
    os.system("cls" if os.name == "nt" else "clear")

    print("╔══════════════════════════════════════════════════════╗")
    print("║         EdgeBot Reflex — Live Dashboard              ║")
    print("╠══════════════════════════════════════════════════════╣")
    print(f"║  Distance : {dist:6.1f} cm   Zone: {zone}            ║")
    print(f"║  [{bar}]  ║")
    print("╠══════════════════════════════════════════════════════╣")
    print("║  LEDS (Wokwi)                                        ║")
    print(f"║    🔴 RED   (DANGER/Mamba STOP) : {led_display(led_red)}                  ║")
    print(f"║    🟢 GREEN (OK/Mamba move)     : {led_display(led_green)}                  ║")
    print(f"║    🔵 BLUE  (PLAN/SmolVLA)      : {led_display(led_blue)}                  ║")
    print("╠══════════════════════════════════════════════════════╣")
    print("║  MODEL DECISIONS                                     ║")
    print(f"║    Falcon Mamba  : {m_cmd:<10}  (fast reflex <10ms)  ║")
    print(f"║    SmolVLA       : {s_cmd:<14}  (plan ~200ms)    ║")
    print(f"║    Arbiter chose : {a_cmd:<14}                   ║")
    print("╠══════════════════════════════════════════════════════╣")
    print("║  RECENT LOG                                          ║")
    with log_lock:
        lines = list(log_lines)
    for l in lines[-5:]:
        print(f"║{l:<54}║")
    # pad to always show 5 lines
    for _ in range(5 - len(lines[-5:])):
        print(f"║{'':<54}║")
    print("╚══════════════════════════════════════════════════════╝")
    print("  Press Ctrl+C to stop.")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ser = FakeSerial()

    # Try to find a real COM port (works if Wokwi exposes one)
    try:
        import serial
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            try:
                import serial as _s
                s = _s.Serial(p.device, 9600, timeout=2)
                time.sleep(0.5)
                raw = s.read(256).decode(errors="ignore")
                s.close()
                if "dist_cm" in raw or "status" in raw:
                    ser = _s.Serial(p.device, 9600, timeout=0.1)
                    print(f"Connected to real ESP32 on {p.device}!")
                    time.sleep(1)
                    break
            except Exception:
                pass
    except ImportError:
        pass

    threads = [
        threading.Thread(target=serial_reader_thread, args=(ser,), daemon=True),
        threading.Thread(target=mamba_thread,          args=(ser,), daemon=True),
        threading.Thread(target=smolvla_thread,        args=(ser,), daemon=True),
    ]
    for t in threads:
        t.start()

    time.sleep(0.3)   # let threads populate state

    try:
        while True:
            draw_dashboard()
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()