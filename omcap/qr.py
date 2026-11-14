"""Minimal QR code encoder (byte mode, error correction level M, versions 1-6 = up to 106 bytes), no dependencies.

Used to show the phone link (REQ-F47) as a QR code on the computer. Follows ISO/IEC 18004:
Reed-Solomon over GF(256) with polynomial 0x11D, the eight data masks with the standard penalty rules,
format information with BCH(15,5). Versions 1-6 are checked against the macOS QR reader (CoreImage);
version 7 and up (version information block) are left out on purpose – the phone link needs version 4.
"""

# (total codewords, EC codewords per block, blocks in group 1, data cw per block g1, blocks g2, data cw g2), level M
_M = {
    1: (26, 10, 1, 16, 0, 0), 2: (44, 16, 1, 28, 0, 0), 3: (70, 26, 1, 44, 0, 0), 4: (100, 18, 2, 32, 0, 0),
    5: (134, 24, 2, 43, 0, 0), 6: (172, 16, 4, 27, 0, 0),
}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34]}

# GF(256) tables
_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gmul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(n):
    g = [1]
    for i in range(n):
        g = [a ^ b for a, b in zip(g + [0], [0] + [_gmul(c, _EXP[i]) for c in g])]
    return g


def _rs_remainder(data, n):
    gen = _rs_generator(n)
    rem = list(data) + [0] * n
    for i in range(len(data)):
        c = rem[i]
        if c:
            for j in range(1, len(gen)):
                rem[i + j] ^= _gmul(gen[j], c)
    return rem[len(data):]


def _data_capacity(v):
    _, _, b1, d1, b2, d2 = _M[v]
    return b1 * d1 + b2 * d2


def _codewords(text):
    data = text.encode("utf-8")
    count_bits = 8  # byte mode, versions 1-9
    for v in _M:
        if 4 + count_bits + 8 * len(data) <= 8 * _data_capacity(v):
            break
    else:
        raise ValueError("Text too long for this QR encoder (106 bytes at most)")
    bits = "0100" + format(len(data), "0%db" % count_bits) + "".join(format(b, "08b") for b in data)
    cap = 8 * _data_capacity(v)
    bits += "0" * min(4, cap - len(bits))
    bits += "0" * (-len(bits) % 8)
    words = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    while len(words) < cap // 8:
        words.append(pad[(len(words) - len(bits) // 8) % 2])
    _, ec, b1, d1, b2, d2 = _M[v]
    blocks, pos = [], 0
    for count, size in ((b1, d1), (b2, d2)):
        for _ in range(count):
            blocks.append(words[pos:pos + size])
            pos += size
    ecs = [_rs_remainder(b, ec) for b in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        out += [b[i] for b in blocks if i < len(b)]
    for i in range(ec):
        out += [e[i] for e in ecs]
    return v, out


def _bch(value, poly, bits):
    v = value << (bits - 1)
    while v.bit_length() >= bits:
        v ^= poly << (v.bit_length() - bits)
    return v


def _place(v, codewords, mask):
    n = 17 + 4 * v
    m = [[None] * n for _ in range(n)]

    def finder(r, c):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                rr, cc = r + dr, c + dc
                if 0 <= rr < n and 0 <= cc < n:
                    inside = 0 <= dr <= 6 and 0 <= dc <= 6
                    ring = inside and (dr in (0, 6) or dc in (0, 6))
                    core = 2 <= dr <= 4 and 2 <= dc <= 4
                    m[rr][cc] = bool(ring or core)
    finder(0, 0)
    finder(0, n - 7)
    finder(n - 7, 0)
    for i in range(8, n - 8):
        m[6][i] = m[i][6] = i % 2 == 0
    for r in _ALIGN[v]:
        for c in _ALIGN[v]:
            if m[r][c] is not None:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = max(abs(dr), abs(dc)) != 1
    m[n - 8][8] = True  # dark module
    reserved = set()
    for i in range(9):
        reserved |= {(8, i), (i, 8)}
    for i in range(8):
        reserved |= {(8, n - 1 - i), (n - 1 - i, 8)}
    for r, c in reserved:
        if m[r][c] is None:
            m[r][c] = False
    func = [[m[r][c] is not None or (r, c) in reserved for c in range(n)] for r in range(n)]
    bits = "".join(format(w, "08b") for w in codewords)
    k, upward = 0, True
    col = n - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(n - 1, -1, -1) if upward else range(n)
        for r in rows:
            for c in (col, col - 1):
                if func[r][c]:
                    continue
                bit = k < len(bits) and bits[k] == "1"
                k += 1
                if _mask_bit(mask, r, c):
                    bit = not bit
                m[r][c] = bit
        upward = not upward
        col -= 2
    fmt = (0b00 << 3 | mask)  # level M = 00
    f = ((fmt << 10) | _bch(fmt, 0b10100110111, 11)) ^ 0b101010000010010
    fb = [(f >> i) & 1 for i in range(14, -1, -1)]
    pos1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8),
            (1, 8), (0, 8)]
    pos2 = [(n - 1, 8), (n - 2, 8), (n - 3, 8), (n - 4, 8), (n - 5, 8), (n - 6, 8), (n - 7, 8), (8, n - 8),
            (8, n - 7), (8, n - 6), (8, n - 5), (8, n - 4), (8, n - 3), (8, n - 2), (8, n - 1)]
    for i, b in enumerate(fb):
        for r, c in (pos1[i], pos2[i]):
            m[r][c] = bool(b)
    return m


def _mask_bit(mask, r, c):
    return [
        (r + c) % 2 == 0, r % 2 == 0, c % 3 == 0, (r + c) % 3 == 0, (r // 2 + c // 3) % 2 == 0,
        (r * c) % 2 + (r * c) % 3 == 0, ((r * c) % 2 + (r * c) % 3) % 2 == 0, ((r + c) % 2 + (r * c) % 3) % 2 == 0,
    ][mask]


def _penalty(m):
    n, score = len(m), 0
    for grid in (m, [list(x) for x in zip(*m)]):
        for row in grid:
            run, prev = 0, None
            for b in row:
                if b == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += run - 2
                    run, prev = 1, b
            if run >= 5:
                score += run - 2
            s = "".join("1" if b else "0" for b in row)
            score += 40 * (s.count("10111010000") + s.count("00001011101"))
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r + 1][c] == m[r][c + 1] == m[r + 1][c + 1]:
                score += 3
    dark = sum(b for row in m for b in row)
    score += 10 * (abs(dark * 20 - n * n * 10) // (n * n))
    return score


def encode(text):
    """Module matrix (list of rows of bools, True = dark) for `text`."""
    v, words = _codewords(text)
    return min((_place(v, words, k) for k in range(8)), key=_penalty)


def svg(text, scale=6, quiet=4):
    """The QR code as an SVG string (black on white, with a quiet zone)."""
    m = encode(text)
    n = len(m) + 2 * quiet
    rects = "".join('<rect x="%d" y="%d" width="1" height="1"/>' % (c + quiet, r + quiet)
                    for r, row in enumerate(m) for c, b in enumerate(row) if b)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
            'shape-rendering="crispEdges"><rect width="%d" height="%d" fill="#fff"/><g fill="#000">%s</g></svg>'
            % (n, n, n * scale, n * scale, n, n, rects))
