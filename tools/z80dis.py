#!/usr/bin/env python3
"""Small Z80 disassembler for reverse-engineering the ZX originals.

Usage:
  python3 tools/z80dis.py FILE.bin ORG [START] [END] [--hex]

ORG/START/END are decimal or 0x hex; START/END are addresses (default:
whole file).  Prints one instruction per line: address, bytes, mnemonic.
"""
import sys

R8 = ["b", "c", "d", "e", "h", "l", "(hl)", "a"]
R16 = ["bc", "de", "hl", "sp"]
R16P = ["bc", "de", "hl", "af"]
CC = ["nz", "z", "nc", "c", "po", "pe", "p", "m"]
ALU = ["add a,", "adc a,", "sub ", "sbc a,", "and ", "xor ", "or ", "cp "]
ROT = ["rlc", "rrc", "rl", "rr", "sla", "sra", "sll", "srl"]

X0Z7 = ["rlca", "rrca", "rla", "rra", "daa", "cpl", "scf", "ccf"]
BLI = {
    (4, 0): "ldi", (4, 1): "cpi", (4, 2): "ini", (4, 3): "outi",
    (5, 0): "ldd", (5, 1): "cpd", (5, 2): "ind", (5, 3): "outd",
    (6, 0): "ldir", (6, 1): "cpir", (6, 2): "inir", (6, 3): "otir",
    (7, 0): "lddr", (7, 1): "cpdr", (7, 2): "indr", (7, 3): "otdr",
}


class Dis:
    def __init__(self, mem, org):
        self.mem = mem
        self.org = org

    def byte(self):
        b = self.mem[self.pc - self.org]
        self.pc += 1
        return b

    def word(self):
        lo = self.byte()
        return lo | (self.byte() << 8)

    def disp(self):
        d = self.byte()
        return d - 256 if d >= 128 else d

    def one(self, pc):
        """Disassemble one instruction at pc -> (text, next_pc)."""
        self.pc = pc
        self.ixy = None
        text = self._op()
        return text, self.pc

    def _r8(self, i):
        if self.ixy and i != 6:
            return {"h": self.ixy + "h", "l": self.ixy + "l"}.get(R8[i], R8[i])
        if self.ixy and i == 6:
            d = self.disp()
            return f"({self.ixy}{d:+d})"
        return R8[i]

    def _rp(self, i, alt=False):
        tbl = R16P if alt else R16
        n = tbl[i]
        if self.ixy and n == "hl":
            return self.ixy
        return n

    def _op(self):
        op = self.byte()
        if op == 0xDD:
            self.ixy = "ix"
            op = self.byte()
        elif op == 0xFD:
            self.ixy = "iy"
            op = self.byte()
        if op == 0xCB:
            return self._cb()
        if op == 0xED:
            return self._ed()
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        if x == 0:
            if z == 0:
                if y == 0:
                    return "nop"
                if y == 1:
                    return "ex af,af'"
                if y == 2:
                    return f"djnz {self.pc + self.disp() + 1 - 0:#06x}" if False else f"djnz {self._rel()}"
                if y == 3:
                    return f"jr {self._rel()}"
                return f"jr {CC[y-4]},{self._rel()}"
            if z == 1:
                if q == 0:
                    return f"ld {self._rp(p)},{self.word():#06x}"
                return f"add {self._rp(2)},{self._rp(p)}"
            if z == 2:
                tgt = self._rp(2)
                tbl = {
                    (0, 0): "ld (bc),a", (0, 1): "ld a,(bc)",
                    (1, 0): "ld (de),a", (1, 1): "ld a,(de)",
                }
                if (p, q) in tbl:
                    return tbl[(p, q)]
                if p == 2:
                    return (f"ld ({self.word():#06x}),{tgt}" if q == 0
                            else f"ld {tgt},({self.word():#06x})")
                return (f"ld ({self.word():#06x}),a" if q == 0
                        else f"ld a,({self.word():#06x})")
            if z == 3:
                return f"{'inc' if q == 0 else 'dec'} {self._rp(p)}"
            if z == 4:
                return f"inc {self._r8(y)}"
            if z == 5:
                return f"dec {self._r8(y)}"
            if z == 6:
                t = self._r8(y)
                return f"ld {t},{self.byte():#04x}"
            return X0Z7[y]
        if x == 1:
            if op == 0x76:
                return "halt"
            # ld r,r' with ix/iy displacement rules
            if self.ixy and (y == 6 or z == 6):
                if y == 6:
                    return f"ld {self._r8(6)},{R8[z]}"
                return f"ld {R8[y]},{self._r8(6)}"
            return f"ld {self._r8(y)},{self._r8(z)}"
        if x == 2:
            return f"{ALU[y]}{self._r8(z)}"
        # x == 3
        if z == 0:
            return f"ret {CC[y]}"
        if z == 1:
            if q == 0:
                return f"pop {self._rp(p, alt=True)}"
            return ["ret", "exx", f"jp ({self._rp(2)})", "ld sp," + self._rp(2)][p]
        if z == 2:
            return f"jp {CC[y]},{self.word():#06x}"
        if z == 3:
            if y == 0:
                return f"jp {self.word():#06x}"
            if y == 2:
                return f"out ({self.byte():#04x}),a"
            if y == 3:
                return f"in a,({self.byte():#04x})"
            if y == 4:
                return f"ex (sp),{self._rp(2)}"
            if y == 5:
                return "ex de,hl"
            if y == 6:
                return "di"
            return "ei"
        if z == 4:
            return f"call {CC[y]},{self.word():#06x}"
        if z == 5:
            if q == 0:
                return f"push {self._rp(p, alt=True)}"
            return f"call {self.word():#06x}"
        if z == 6:
            return f"{ALU[y]}{self.byte():#04x}"
        return f"rst {y*8:#04x}"

    def _rel(self):
        d = self.disp()
        return f"{(self.pc + d) & 0xFFFF:#06x}"

    def _cb(self):
        if self.ixy:
            d = self.disp()
            op = self.byte()
            x, y, z = op >> 6, (op >> 3) & 7, op & 7
            tgt = f"({self.ixy}{d:+d})"
            extra = "" if z == 6 else f",{R8[z]}"
            if x == 0:
                return f"{ROT[y]} {tgt}{extra}"
            if x == 1:
                return f"bit {y},{tgt}"
            if x == 2:
                return f"res {y},{tgt}{extra}"
            return f"set {y},{tgt}{extra}"
        op = self.byte()
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        if x == 0:
            return f"{ROT[y]} {R8[z]}"
        if x == 1:
            return f"bit {y},{R8[z]}"
        if x == 2:
            return f"res {y},{R8[z]}"
        return f"set {y},{R8[z]}"

    def _ed(self):
        op = self.byte()
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        if x == 2 and (y, z) in BLI:
            return BLI[(y, z)]
        if x != 1:
            return f"db 0xed,{op:#04x}"
        if z == 0:
            return f"in {'f' if y == 6 else R8[y]},(c)"
        if z == 1:
            return f"out (c),{'0' if y == 6 else R8[y]}"
        if z == 2:
            return f"{'sbc' if q == 0 else 'adc'} hl,{R16[p]}"
        if z == 3:
            if q == 0:
                return f"ld ({self.word():#06x}),{R16[p]}"
            return f"ld {R16[p]},({self.word():#06x})"
        if z == 4:
            return "neg"
        if z == 5:
            return "retn" if y != 1 else "reti"
        if z == 6:
            return f"im {[0,0,1,2][y & 3]}"
        return ["ld i,a", "ld r,a", "ld a,i", "ld a,r",
                "rrd", "rld", "nop*", "nop*"][y]


def parse_num(s):
    return int(s, 16) if s.lower().startswith("0x") else int(s)


def main():
    args = [a for a in sys.argv[1:] if a != "--hex"]
    show_hex = "--hex" in sys.argv
    if len(args) < 2:
        print(__doc__)
        return 1
    mem = open(args[0], "rb").read()
    org = parse_num(args[1])
    start = parse_num(args[2]) if len(args) > 2 else org
    end = parse_num(args[3]) if len(args) > 3 else org + len(mem)
    d = Dis(mem, org)
    pc = start
    while pc < end and pc - org < len(mem):
        text, npc = d.one(pc)
        raw = mem[pc - org : npc - org].hex()
        if show_hex:
            print(f"{pc:04x}({pc:5d}): {raw:<12s} {text}")
        else:
            print(f"{pc:04x}: {raw:<12s} {text}")
        pc = npc
    return 0


if __name__ == "__main__":
    sys.exit(main())
