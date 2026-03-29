#!/usr/bin/env python3
"""Relaunch all Firefox instances with dbus-run-session on Thor.
Then start sft_gen_bot for each platform."""
import os, subprocess, time, sys

DISPLAYS = {
    6: ("gemini", "https://gemini.google.com/app", "ff-profile-gemini"),
    7: ("grok", "https://grok.com/", "ff-profile-grok"),
    8: ("claude", "https://claude.ai/new?incognito", "ff-profile-claude4"),
    9: ("perplexity", "https://www.perplexity.ai/", "ff-profile-perplexity"),
    10: ("claude", "https://claude.ai/new?incognito", "ff-profile-claude2"),
    11: ("claude", "https://claude.ai/new?incognito", "ff-profile-claude3"),
    13: ("chatgpt", "https://chatgpt.com/?temporary-chat=true", "ff-profile-chatgpt2"),
}

print("=== FULL CLEANUP — kill ALL user automation processes ===")

# 1. Kill all bots
subprocess.run(["pkill", "-9", "-f", "sft_gen_bot"], capture_output=True)
subprocess.run(["pkill", "-9", "-f", "training_gen_bot"], capture_output=True)
time.sleep(1)

# 2. Kill ALL Firefox (no exceptions)
subprocess.run(["pkill", "-9", "firefox"], capture_output=True)
time.sleep(1)
subprocess.run(["pkill", "-9", "firefox"], capture_output=True)  # double tap for contentproc
time.sleep(1)

# 3. Kill ALL at-spi-bus-launcher processes
subprocess.run(["pkill", "-9", "-f", "at-spi-bus-launcher"], capture_output=True)

# 4. Kill ALL dbus-run-session wrappers
subprocess.run(["pkill", "-9", "-f", "dbus-run-session"], capture_output=True)

# 5. Kill ALL user-owned dbus-daemon (NOT root system ones)
my_uid = os.getuid()
r = subprocess.run(["ps", "-u", str(my_uid), "-o", "pid,comm"],
                    capture_output=True, text=True)
for line in r.stdout.strip().split('\n'):
    if 'dbus-daemon' in line:
        try:
            pid = int(line.strip().split()[0])
            os.kill(pid, 9)
        except: pass

time.sleep(2)

# 6. Clean ALL lock files and stale bus files
for d in range(20):
    try: os.remove(f"/tmp/a11y_bus_:{d}")
    except: pass
for entry in os.listdir("/tmp"):
    if entry.startswith("ff-profile-"):
        for lock in [".parentlock", "lock"]:
            try: os.remove(f"/tmp/{entry}/{lock}")
            except: pass

# 7. Verify cleanup
r = subprocess.run(["bash", "-c", "cat /proc/sys/fs/file-nr | awk '{print $1}'"],
                    capture_output=True, text=True)
print(f"Open files after cleanup: {r.stdout.strip()}")
r = subprocess.run(["bash", "-c", "ps aux | grep '[d]bus' | wc -l"],
                    capture_output=True, text=True)
print(f"dbus processes after cleanup: {r.stdout.strip()}")

time.sleep(1)
print("=== Launching Firefox with dbus-run-session ===")

for d, (plat, url, prof) in DISPLAYS.items():
    # Write individual launch script — no quoting issues
    script = (
        "#!/bin/bash\n"
        f"export DISPLAY=:{d}\n"
        "/usr/libexec/at-spi-bus-launcher --launch-immediately &\n"
        "sleep 2\n"
        f"A11Y=$(xprop -display :{d} -root AT_SPI_BUS 2>/dev/null "
        "| sed 's/.*= \"//' | sed 's/\"$//')\n"
        f"echo \"$A11Y\" > /tmp/a11y_bus_:{d}\n"
        "GTK_USE_PORTAL=0 LIBGL_ALWAYS_SOFTWARE=1 "
        "MOZ_DISABLE_RDD_SANDBOX=1 MOZ_DISABLE_GPU_SANDBOXING=1 "
        f"GDK_BACKEND=x11 firefox --no-remote --profile /tmp/{prof} "
        f"'{url}' &\n"
        "FIREFOX_PID=$!\n"
        f"echo $FIREFOX_PID > /tmp/firefox_pid_:{d}\n"
        "wait $FIREFOX_PID\n"
    )
    script_path = f"/tmp/launch_ff_{d}.sh"
    with open(script_path, "w") as f:
        f.write(script)
    os.chmod(script_path, 0o755)

    subprocess.Popen(
        ["nohup", "dbus-run-session", "--", "bash", script_path],
        stdout=open(f"/tmp/launch_{d}.log", "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"  :{d} ({plat}) launched")
    time.sleep(4)

print("=== Waiting for Firefox to load ===")
time.sleep(15)

for d in DISPLAYS:
    env = {**os.environ, "DISPLAY": f":{d}"}
    try:
        r = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            env=env, capture_output=True, text=True, timeout=3,
        )
        title = r.stdout.strip() or "NO WINDOW"
    except:
        title = "ERROR"
    print(f"  :{d} {title}")

print("\n=== Starting bots ===")
for d, (plat, url, prof) in DISPLAYS.items():
    session = f"sft-{plat}{d}"
    # Get DBUS from Firefox
    try:
        with open(f"/tmp/firefox_pid_:{d}") as f:
            ff_pid = int(f.read().strip())
        with open(f"/proc/{ff_pid}/environ", "rb") as f:
            env_data = f.read().decode(errors="replace")
        dbus = "unix:path=/run/user/1000/bus"
        for entry in env_data.split("\0"):
            if entry.startswith("DBUS_SESSION_BUS_ADDRESS="):
                dbus = entry.split("=", 1)[1]
                break
    except:
        dbus = "unix:path=/run/user/1000/bus"

    subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)
    time.sleep(0.5)
    cmd = (
        f"cd ~/taeys-hands && DISPLAY=:{d} "
        f"DBUS_SESSION_BUS_ADDRESS={dbus} "
        f"TAEY_NOTIFY_NODE=taeys-hands REDIS_HOST=10.0.0.163 "
        f"PYTHONPATH=~/embedding-server "
        f"python3 agents/sft_gen_bot.py --round sft --platforms {plat} "
        f"2>&1 | tee /tmp/{session}.log"
    )
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session, cmd],
        capture_output=True,
    )
    print(f"  {session} started (DBUS={dbus[:40]}...)")
    time.sleep(2)

print("\n=== DONE ===")
