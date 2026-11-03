#!/usr/bin/env python3
"""Press Esc repeatedly while GRUB's hidden timeout runs and capture the screen.
usage: grub-esc.py IMAGE.raw OUTDIR LABEL"""
import os, socket, subprocess, sys, time
image, out, label = sys.argv[1:4]
mon = os.path.join(out, f'{label}.mon')
overlay = os.path.join(out, f'{label}.qcow2')
subprocess.run(['qemu-img', 'create', '-q', '-f', 'qcow2', '-F', 'raw', '-b', os.path.abspath(image), overlay], check=True)
q = subprocess.Popen(['qemu-system-aarch64', '-M', 'virt', '-accel', 'hvf', '-cpu', 'host', '-smp', '2', '-m', '2048',
    '-bios', '/opt/homebrew/share/qemu/edk2-aarch64-code.fd', '-drive', f'file={overlay},if=virtio,format=qcow2',
    '-device', 'virtio-gpu-pci', '-device', 'qemu-xhci', '-device', 'usb-kbd', '-display', 'none',
    '-serial', f'file:{os.path.join(out, label + "-serial.log")}', '-monitor', f'unix:{mon},server,nowait', '-no-reboot'])
def m(cmd):
    s = socket.socket(socket.AF_UNIX); s.connect(mon); s.settimeout(0.5)
    try: s.recv(4096)
    except socket.timeout: pass
    s.sendall((cmd + '\n').encode()); time.sleep(0.1); s.close()
t0 = time.time()
while not os.path.exists(mon): time.sleep(0.05)
time.sleep(0.3)
serial = os.path.join(out, label + '-serial.log')
# GRUB is running once BdsDxe has started the boot option; Esc before that
# opens the firmware setup instead.
while 'BdsDxe: starting' not in open(serial, errors='replace').read() and time.time() - t0 < 30:
    time.sleep(0.05)
t1 = time.time()
while time.time() - t1 < 2.5:
    m('sendkey esc')
    time.sleep(0.1)
time.sleep(2)
ppm = os.path.join(out, f'{label}-menu.ppm')
m(f'screendump {ppm}'); time.sleep(1)
m('quit'); q.wait(timeout=20); os.unlink(overlay)
subprocess.run(['sips', '-s', 'format', 'png', ppm, '--out', ppm[:-4] + '.png'], check=True, capture_output=True); os.unlink(ppm)
print(ppm[:-4] + '.png')
