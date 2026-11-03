#!/usr/bin/env python3
"""Boot a UEFI disk image with a LUKS2 root under QEMU (hvf, virtio-gpu,
edk2) and drive the Plymouth passphrase prompt through the QEMU monitor.
Adapted from neo-plymouth-20261103/luks-vm/run.py (Fedora, direct kernel).

usage: run.py IMAGE.raw OUTDIR LABEL [PASSPHRASE]
Writes LABEL-serial.log, LABEL-NN-<step>.png, LABEL-result.txt in OUTDIR.
"""
import os, socket, subprocess, sys, time

image, out, label = sys.argv[1], sys.argv[2], sys.argv[3]
passphrase = sys.argv[4] if len(sys.argv) > 4 else 'aurora-luks-test'
os.makedirs(out, exist_ok=True)
mon = os.path.join(out, f'{label}.mon')
serial = os.path.join(out, f'{label}-serial.log')
for p in (mon, serial):
    if os.path.exists(p):
        os.unlink(p)
# A copy-on-write overlay keeps the image pristine for reruns.
overlay = os.path.join(out, f'{label}.qcow2')
subprocess.run(['qemu-img', 'create', '-q', '-f', 'qcow2', '-F', 'raw', '-b',
                os.path.abspath(image), overlay], check=True)
qemu = subprocess.Popen([
    'qemu-system-aarch64', '-M', 'virt', '-accel', 'hvf', '-cpu', 'host',
    '-smp', '2', '-m', '2048',
    '-bios', '/opt/homebrew/share/qemu/edk2-aarch64-code.fd',
    '-drive', f'file={overlay},if=virtio,format=qcow2',
    '-device', 'virtio-gpu-pci', '-device', 'virtio-keyboard-pci',
    '-display', 'none', '-serial', f'file:{serial}',
    '-monitor', f'unix:{mon},server,nowait', '-no-reboot'])

def monitor(cmd):
    s = socket.socket(socket.AF_UNIX)
    s.connect(mon)
    s.settimeout(2)
    try:
        s.recv(4096)
    except socket.timeout:
        pass
    s.sendall((cmd + '\n').encode())
    time.sleep(0.3)
    try:
        s.recv(65536)
    except socket.timeout:
        pass
    s.close()

shots = []
def shot(step):
    n = len(shots) + 1
    path = os.path.join(out, f'{label}-{n:02d}-{step}.ppm')
    monitor(f'screendump {path}')
    shots.append((path, step, time.time() - t0))

def keys(text):
    names = {'-': 'minus', ' ': 'spc'}
    for ch in text:
        monitor(f'sendkey {names.get(ch, ch)}')
        time.sleep(0.12)

def serial_text():
    try:
        return open(serial, errors='replace').read()
    except FileNotFoundError:
        return ''

t0 = time.time()
while not os.path.exists(mon) and time.time() - t0 < 10:
    time.sleep(0.1)
time.sleep(0.5)
# One screendump a second until the prompt has had time to appear.
for t in range(1, 31):
    while time.time() - t0 < t:
        time.sleep(0.05)
    shot(f'boot{t:02d}s')
keys('wrong')
shot('typed-wrong')
for _ in range(5):
    monitor('sendkey backspace'); time.sleep(0.12)
shot('after-backspace')
monitor('sendkey esc'); time.sleep(1.0); shot('esc-details')
monitor('sendkey esc'); time.sleep(1.0); shot('esc-back')
keys(passphrase)
shot('typed-pass')
monitor('sendkey ret')
t_ret = time.time()
deadline = time.time() + 120
while time.time() < deadline and 'AURORA-REPORT-END' not in serial_text():
    time.sleep(0.5)
unlocked = 'AURORA-UNLOCK-OK' in serial_text()
deadline = time.time() + 30
while time.time() < deadline and 'login:' not in serial_text():
    time.sleep(0.5)
time.sleep(2)
shot('end-login')
login = 'login:' in serial_text()
monitor('quit')
qemu.wait(timeout=20)
for path, _, _ in shots:
    if os.path.exists(path):
        subprocess.run(['sips', '-s', 'format', 'png', path, '--out', path[:-4] + '.png'],
                       check=True, capture_output=True)
        os.unlink(path)
with open(os.path.join(out, f'{label}-shots.tsv'), 'w') as f:
    for path, step, t in shots:
        f.write(f'{os.path.basename(path)[:-4]}.png\t{step}\t{t:.2f}\n')
os.unlink(overlay)
result = (f'{label}: unlock {"OK" if unlocked else "FAILED"}, login prompt {"OK" if login else "MISSING"}, '
          f'report {time.time() - t0:.1f} s after start, enter sent at {t_ret - t0:.1f} s')
open(os.path.join(out, f'{label}-result.txt'), 'w').write(result + '\n')
print(result)
