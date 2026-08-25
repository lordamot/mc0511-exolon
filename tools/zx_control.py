#!/usr/bin/env python3
"""Launch and drive the ZEsarUX ZX Spectrum emulator (bin/zesarux) via its
ZRCP remote-control protocol.

Usage:
    zx_control.py launch --trd FILE.trd [--machine Pentagon] [--port 10000] [--window]
    zx_control.py stop [--port 10000]
    zx_control.py status [--port 10000]
    zx_control.py reset [--port 10000]
    zx_control.py screenshot OUT.bmp [--port 10000]
    zx_control.py ocr [--port 10000]
    zx_control.py press KEYSPEC [KEYSPEC ...] [--port 10000]
    zx_control.py boot-trdos [--port 10000]
    zx_control.py cat [--port 10000]
    zx_control.py raw "ZRCP COMMAND" [--port 10000]

KEYSPEC is one or more key names joined by '+' for a simultaneous combo,
e.g. ENTER, CAPS_SHIFT+6, SYM_SHIFT+9. See KEYMAP below for all key names.
Multiple KEYSPEC arguments are pressed one after another.

See .claude/docs/tools/zx-emulate.md and .claude/docs/tools/zx-keyboard.md
for the full story on why this drives the keyboard the way it does.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ZESARUX_DIR = REPO_ROOT / "bin" / "zesarux"
ZESARUX_RUN = ZESARUX_DIR / "run.sh"
STATE_DIR = REPO_ROOT / "tmp" / "zx_control"

PROMPT = b"command> "
PROMPT_STEP = b"command@cpu-step> "

# Physical keyboard matrix: name -> (row index 0-7, bit within that row's byte).
# Row order / bit assignment matches ZEsarUX's set-ui-io-ports / get-ui-io-ports:
#   row0 0xFEFE: bit4 V, bit3 C, bit2 X, bit1 Z, bit0 CAPS_SHIFT
#   row1 0xFDFE: bit4 G, bit3 F, bit2 D, bit1 S, bit0 A
#   row2 0xFBFE: bit4 T, bit3 R, bit2 E, bit1 W, bit0 Q
#   row3 0xF7FE: bit4 5, bit3 4, bit2 3, bit1 2, bit0 1
#   row4 0xEFFE: bit4 6, bit3 7, bit2 8, bit1 9, bit0 0
#   row5 0xDFFE: bit4 Y, bit3 U, bit2 I, bit1 O, bit0 P
#   row6 0xBFFE: bit4 H, bit3 J, bit2 K, bit1 L, bit0 ENTER
#   row7 0x7FFE: bit4 B, bit3 N, bit2 M, bit1 SYM_SHIFT, bit0 SPACE
KEYMAP = {
    "CAPS_SHIFT": (0, 0x01), "Z": (0, 0x02), "X": (0, 0x04), "C": (0, 0x08), "V": (0, 0x10),
    "A": (1, 0x01), "S": (1, 0x02), "D": (1, 0x04), "F": (1, 0x08), "G": (1, 0x10),
    "Q": (2, 0x01), "W": (2, 0x02), "E": (2, 0x04), "R": (2, 0x08), "T": (2, 0x10),
    "1": (3, 0x01), "2": (3, 0x02), "3": (3, 0x04), "4": (3, 0x08), "5": (3, 0x10),
    "0": (4, 0x01), "9": (4, 0x02), "8": (4, 0x04), "7": (4, 0x08), "6": (4, 0x10),
    "P": (5, 0x01), "O": (5, 0x02), "I": (5, 0x04), "U": (5, 0x08), "Y": (5, 0x10),
    "ENTER": (6, 0x01), "L": (6, 0x02), "K": (6, 0x04), "J": (6, 0x08), "H": (6, 0x10),
    "SPACE": (7, 0x01), "SYM_SHIFT": (7, 0x02), "M": (7, 0x04), "N": (7, 0x08), "B": (7, 0x10),
}

IDLE_PORTS = [0xFF] * 8


class ZRCPError(RuntimeError):
    pass


class ZRCP:
    """Minimal ZEsarUX Remote Command Protocol client.

    Reads every response up to the literal 'command> ' prompt terminator
    rather than until a socket timeout. Getting this wrong (looping recv()
    until it times out) silently adds ~2s to every round trip -- easy to
    mistake for "the emulator's speed is unstable". See zx-keyboard.md.
    """

    def __init__(self, host="127.0.0.1", port=10000, connect_timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=connect_timeout)
        self._read_until_prompt()
        self.tstates_per_frame = self._detect_tstates_per_frame()

    def _read_until_prompt(self, timeout=3.0):
        self.sock.settimeout(timeout)
        out = b""
        t0 = time.time()
        while True:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                raise ZRCPError(f"no prompt within {timeout}s, got: {out!r}")
            if not chunk:
                break
            out += chunk
            if out.endswith(PROMPT_STEP):
                return out[: -len(PROMPT_STEP)].decode(errors="replace").rstrip("\n")
            if out.endswith(PROMPT):
                break
            if time.time() - t0 > timeout:
                raise ZRCPError(f"no prompt within {timeout}s, got: {out!r}")
        return out[: -len(PROMPT)].decode(errors="replace").rstrip("\n")

    def cmd(self, command, timeout=3.0):
        self.sock.sendall((command + "\n").encode())
        return self._read_until_prompt(timeout=timeout)

    def _detect_tstates_per_frame(self):
        try:
            hz = int(self.cmd("get-cpu-frequency").strip())
            return hz // 50
        except Exception:
            return 71680  # Pentagon / 128k default (3584000 Hz / 50 Hz)

    def ports_hex(self, rows, joystick=0):
        return (bytes(rows) + bytes([joystick])).hex().upper()

    def wait_tstates(self, n, timeout=2.0):
        self.cmd("reset-tstates-partial")
        t0 = time.time()
        while True:
            line = self.cmd("get-tstates-partial").strip().splitlines()[0]
            if "OVERFLOW" not in line and int(line) >= n:
                return int(line)
            if time.time() - t0 > timeout:
                return None

    def press(self, keyspec, frames_held=1, frames_release=3):
        """Press one KEYSPEC ('+'-joined key names) as a short, T-state-gated pulse."""
        rows = IDLE_PORTS.copy()
        for name in keyspec.split("+"):
            name = name.strip().upper()
            if name not in KEYMAP:
                raise ZRCPError(f"unknown key name: {name!r} (see KEYMAP)")
            row, bit = KEYMAP[name]
            rows[row] &= 0xFF & ~bit
        self.cmd(f"set-ui-io-ports {self.ports_hex(rows)}")
        self.wait_tstates(frames_held * self.tstates_per_frame)
        self.cmd(f"set-ui-io-ports {self.ports_hex(IDLE_PORTS)}")
        self.wait_tstates(frames_release * self.tstates_per_frame)

    def press_all(self, keyspecs, frames_held=1, frames_release=3):
        for spec in keyspecs:
            self.press(spec, frames_held=frames_held, frames_release=frames_release)


def state_path(port):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"{port}.json"


def cmd_launch(args):
    if not ZESARUX_RUN.exists():
        sys.exit(f"error: {ZESARUX_RUN} not found")
    if not args.trd and not args.sna and not args.tap:
        sys.exit("error: need --trd, --sna or --tap")

    sp = state_path(args.port)
    if sp.exists():
        old = json.loads(sp.read_text())
        if _pid_alive(old.get("pid")):
            sys.exit(f"error: an instance is already running on port {args.port} (pid {old['pid']})")

    zx_args = [
        str(ZESARUX_RUN),
        "--machine", args.machine,
        "--enable-remoteprotocol", "--remoteprotocol-port", str(args.port),
        "--vo", "xwindows" if args.window else "null",
        "--ao", "null",
    ]
    if args.romfile:
        zx_args += ["--romfile", str(Path(args.romfile).resolve())]
    if args.joystick:
        zx_args += ["--joystickemulated", args.joystick]
    trd_path = None
    if args.trd:
        trd_path = Path(args.trd).resolve()
        if not trd_path.exists():
            sys.exit(f"error: trd file not found: {trd_path}")
        zx_args += ["--enable-betadisk", "--enable-trd", "--trd-file", str(trd_path)]
    if args.tap:
        tap_path = Path(args.tap).resolve()
        if not tap_path.exists():
            sys.exit(f"error: tap file not found: {tap_path}")
        zx_args += ["--tape", str(tap_path)]
        if args.realtape:
            zx_args += ["--realtape", str(tap_path)]
    if args.sna:
        sna_path = Path(args.sna).resolve()
        if not sna_path.exists():
            sys.exit(f"error: sna file not found: {sna_path}")
        zx_args += ["--snap", str(sna_path)]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = STATE_DIR / f"{args.port}.log"
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(
            zx_args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
    sp.write_text(json.dumps({
        "pid": proc.pid, "port": args.port, "trd": str(trd_path), "machine": args.machine,
    }))

    for _ in range(50):
        try:
            z = ZRCP(port=args.port)
            print(f"launched pid={proc.pid} port={args.port} machine={z.cmd('get-current-machine')}")
            return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    sys.exit(f"error: emulator did not start accepting ZRCP connections; see {log_path}")


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cmd_stop(args):
    sp = state_path(args.port)
    if not sp.exists():
        sys.exit(f"error: no known instance on port {args.port}")
    info = json.loads(sp.read_text())
    try:
        z = ZRCP(port=args.port)
        z.cmd("exit-emulator")
    except OSError:
        pass
    if _pid_alive(info.get("pid")):
        time.sleep(0.3)
        if _pid_alive(info["pid"]):
            os.kill(info["pid"], 15)
    sp.unlink(missing_ok=True)
    print(f"stopped port {args.port}")


def cmd_status(args):
    z = ZRCP(port=args.port)
    print("machine:", z.cmd("get-current-machine"))
    print("registers:", z.cmd("get-registers"))
    print("tstates/frame:", z.tstates_per_frame)


def cmd_reset(args):
    z = ZRCP(port=args.port)
    z.cmd("hard-reset-cpu", timeout=5.0)
    time.sleep(1.0)  # boot ROM needs real time to render before it accepts input
    print("reset ok")


def cmd_screenshot(args):
    z = ZRCP(port=args.port)
    out = Path(args.out).resolve()
    z.cmd(f"save-screen {out}", timeout=5.0)
    print(f"saved {out}")


def cmd_ocr(args):
    z = ZRCP(port=args.port)
    print(z.cmd("get-ocr", timeout=5.0))


def cmd_press(args):
    z = ZRCP(port=args.port)
    z.press_all(args.keyspec)
    print("ok")


def cmd_boot_trdos(args):
    """Pentagon-only convenience: hard-reset (so the boot menu starts from
    a known state -- a soft reset-cpu leaves RAM, and thus the menu's
    remembered highlighted entry, untouched), then navigate the boot ROM
    menu down to the TR-DOS entry and select it."""
    z = ZRCP(port=args.port)
    z.cmd("hard-reset-cpu", timeout=5.0)
    time.sleep(1.0)  # boot ROM needs real time to render before it accepts input
    for _ in range(4):
        z.press("CAPS_SHIFT+6")  # down
    z.press("ENTER")
    time.sleep(0.5)
    print(z.cmd("get-ocr", timeout=5.0))


def cmd_cat(args):
    """Type TR-DOS's CAT command: Extended mode (CAPS+SYM together) then
    SYM_SHIFT+9, then Enter. Must already be at a TR-DOS 'A>' prompt."""
    z = ZRCP(port=args.port)
    z.press("CAPS_SHIFT+SYM_SHIFT")
    z.press("SYM_SHIFT+9")
    z.press("ENTER", frames_release=5)
    time.sleep(0.5)
    print(z.cmd("get-ocr", timeout=5.0))


def cmd_raw(args):
    z = ZRCP(port=args.port)
    print(z.cmd(args.command, timeout=10.0))


JOYBITS = {"RIGHT": 1, "LEFT": 2, "DOWN": 4, "UP": 8, "FIRE": 16}

# The game's default keyboard layout: Q up, A down, O left, P right,
# Z..M punch/kick (we use M).  rows_for_joy() renders a kempston-style
# bitmask as keyboard row states so scripts work in the default input
# mode without touching the in-game input-device setting.
JOYKEYS = {1: "P", 2: "O", 4: "A", 8: "Q", 16: "M"}


def rows_for_joy(val):
    rows = IDLE_PORTS.copy()
    for bit, key in JOYKEYS.items():
        if val & bit:
            row, mask = KEYMAP[key]
            rows[row] &= 0xFF & ~mask
    return rows


def cmd_joy(args):
    """Hold a Kempston joystick state for N frames (then release).

    SPEC is '+'-joined direction/fire names, or NONE.  The game must be
    reading Kempston (input type byte = 2).
    """
    z = ZRCP(port=args.port)
    val = 0
    for name in args.spec.split("+"):
        name = name.strip().upper()
        if name == "NONE":
            continue
        if name not in JOYBITS:
            raise ZRCPError(f"unknown joy name {name!r}")
        val |= JOYBITS[name]
    z.cmd(f"set-ui-io-ports {z.ports_hex(rows_for_joy(val), joystick=val)}")
    z.wait_tstates(args.frames * z.tstates_per_frame,
                   timeout=max(2.0, args.frames / 25))
    if not args.hold:
        z.cmd(f"set-ui-io-ports {z.ports_hex(IDLE_PORTS)}")
    print("ok")


def cmd_dump(args):
    """Dump a memory range to a binary file via read-memory (hex pairs)."""
    z = ZRCP(port=args.port)
    addr = int(args.addr, 0)
    length = int(args.length, 0)
    out = bytearray()
    while len(out) < length:
        chunk = min(4096, length - len(out))
        resp = z.cmd(f"read-memory {addr + len(out)} {chunk}", timeout=10.0)
        out += bytes.fromhex(resp.strip())
    Path(args.out).write_bytes(out)
    print(f"wrote {args.out} ({len(out)} bytes from {addr:#06x})")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=10000)
    sub = parser.add_subparsers(dest="action", required=True)

    p = sub.add_parser("launch")
    p.add_argument("--trd")
    p.add_argument("--sna", help="snapshot to load at startup")
    p.add_argument("--tap", help="tape image to insert at startup")
    p.add_argument("--realtape", action="store_true",
                   help="also insert the tape as a 'real tape' signal source "
                        "(needed for custom/turbo loaders)")
    p.add_argument("--romfile", help="alternate machine ROM (e.g. the 48K ROM)")
    p.add_argument("--joystick", default="Kempston",
                   help="emulated joystick type (default Kempston; '' disables)")
    p.add_argument("--machine", default="Pentagon")
    p.add_argument("--window", action="store_true", help="show a visible window (default: headless)")
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("stop")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("reset")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("screenshot")
    p.add_argument("out")
    p.set_defaults(func=cmd_screenshot)

    p = sub.add_parser("ocr")
    p.set_defaults(func=cmd_ocr)

    p = sub.add_parser("press")
    p.add_argument("keyspec", nargs="+")
    p.set_defaults(func=cmd_press)

    p = sub.add_parser("boot-trdos")
    p.set_defaults(func=cmd_boot_trdos)

    p = sub.add_parser("cat")
    p.set_defaults(func=cmd_cat)

    p = sub.add_parser("raw")
    p.add_argument("command")
    p.set_defaults(func=cmd_raw)

    p = sub.add_parser("joy")
    p.add_argument("spec")
    p.add_argument("frames", type=int, nargs="?", default=5)
    p.add_argument("--hold", action="store_true")
    p.set_defaults(func=cmd_joy)

    p = sub.add_parser("dump")
    p.add_argument("addr")
    p.add_argument("length")
    p.add_argument("out")
    p.set_defaults(func=cmd_dump)

    args = parser.parse_args()
    try:
        args.func(args)
    except (ZRCPError, ConnectionRefusedError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
