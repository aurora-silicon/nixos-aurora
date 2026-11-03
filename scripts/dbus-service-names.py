#!/usr/bin/env python3
"""Fail if dbus-broker would find a D-Bus name in more than one service file.

Reads the service directories of a built system's /etc/dbus-1/system.conf and
session.conf in dbus-broker's order. dbus-broker keeps the first file for each
name and logs "Ignoring duplicate name" for every later one.

/run/current-system/sw is the system's system-path. The session bus also reads
XDG_DATA_DIRS, which pam_env sets for every user manager from
/etc/pam/environment. Directories outside the store and system-path are made
at run time (home, per-user profiles, Flatpak exports) and are empty here.
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

SW = "/run/current-system/sw"
STORE = "/nix/store/"
USER, HOME = "owner", "/home/owner"


class System:
    def __init__(self, toplevel):
        self.toplevel = os.path.realpath(toplevel)
        self.sw = os.path.realpath(os.path.join(toplevel, "sw"))
        self.etc = os.path.join(self.toplevel, "etc")

    def local(self, path):
        """Where the running system's path is here, or None if made at run time."""
        if path == SW or path.startswith(SW + "/"):
            return self.sw + path[len(SW):]
        if path.startswith("/etc/"):
            return os.path.join(self.etc, path[len("/etc/"):])
        if path.startswith(STORE):
            return path
        return None

    def data_dirs(self):
        """XDG_DATA_DIRS as pam_env sets it."""
        env = os.path.join(self.etc, "pam/environment")
        text = ""
        if os.path.exists(env):
            with open(env, encoding="utf-8") as f:
                text = f.read()
        m = re.search(r'^\s*XDG_DATA_DIRS\s+DEFAULT="([^"]*)"', text, re.M)
        return m.group(1).replace("@{HOME}", HOME).replace("@{PAM_USER}", USER).split(":") if m else []

    def service_dirs(self, conf, bus):
        """Service directories of a bus configuration file, in load order."""
        dirs = []
        for node in ET.parse(conf).getroot():
            text = (node.text or "").strip()
            if node.tag == "servicedir":
                dirs.append(text)
            elif node.tag == "standard_session_servicedirs" and bus == "session":
                dirs += ["/run/user/1000/dbus-1/services", f"{HOME}/.local/share/dbus-1/services"]
                dirs += [f"{d}/dbus-1/services" for d in self.data_dirs() if d]
            elif node.tag == "standard_system_servicedirs" and bus == "system":
                dirs += [f"{d}/dbus-1/system-services" for d in ("/etc", "/run", SW + "/share")]
            elif node.tag in ("include", "includedir") and self.local(text):
                target = self.local(text)
                files = [target] if node.tag == "include" else [
                    os.path.join(target, f) for f in sorted(os.listdir(target))
                    if f.endswith(".conf") and not f.startswith(".")] if os.path.isdir(target) else []
                for f in files:
                    if os.path.isfile(f):
                        dirs += self.service_dirs(f, bus)
        return dirs

    def scan(self, bus):
        """Every name on the bus, and each (name, kept, ignored) duplicate."""
        names, duplicates = {}, []
        for d in self.service_dirs(os.path.join(self.etc, f"dbus-1/{bus}.conf"), bus):
            here = self.local(d)
            if not here or not os.path.isdir(here):
                continue
            for f in sorted(os.listdir(here)):
                name = service_name(os.path.join(here, f)) if f.endswith(".service") and not f.startswith(".") else None
                if name in names:
                    duplicates.append((name, names[name], os.path.join(d, f)))
                elif name:
                    names[name] = os.path.join(d, f)
        return names, duplicates


def service_name(path):
    group = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("["):
                group = line
            elif group == "[D-BUS Service]" and line.startswith("Name="):
                return line[len("Name="):].strip()
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("system", help="a NixOS toplevel, such as ./result")
    p.add_argument("--names", help="also write each bus and name to this file")
    args = p.parse_args()
    system, found, listed = System(args.system), 0, []
    for bus in ("system", "session"):
        names, duplicates = system.scan(bus)
        listed += [f"{bus} {name}\n" for name in sorted(names)]
        print(f"{bus} bus: {len(names)} names, {len(duplicates)} duplicates")
        for name, kept, ignored in duplicates:
            same = os.path.realpath(system.local(kept)) == os.path.realpath(system.local(ignored))
            print(f"  {name}\n    kept    {kept}\n    ignored {ignored}{' (the same file)' if same else ''}")
        found += len(duplicates)
    if args.names:
        with open(args.names, "w", encoding="utf-8") as f:
            f.writelines(listed)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
