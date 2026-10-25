#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Copy ComfyUI prompt/workflow between existing PNG/WebP files (stdlib only)."""
import argparse
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import zlib

KEYS = {"prompt", "workflow"}
PNG = b"\x89PNG\r\n\x1a\n"


def chunks(data):
    if data.startswith(PNG):
        kind, pos, end = "png", 8, len(data)
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind, pos, end = "webp", 12, len(data)
        if struct.unpack_from("<I", data, 4)[0] + 8 != end:
            raise ValueError("Invalid RIFF size")
    else:
        raise ValueError("PNG or WebP required")
    result = []
    while pos < end:
        if pos + 8 > end:
            raise ValueError("Truncated chunk header")
        if kind == "png":
            size, tag = struct.unpack_from(">I4s", data, pos)
            stop = pos + size + 12
            payload = data[pos + 8:pos + 8 + size]
            if stop > end or zlib.crc32(tag + payload) != struct.unpack_from(">I", data, stop - 4)[0]:
                raise ValueError("Invalid PNG chunk/CRC")
        else:
            tag, size = struct.unpack_from("<4sI", data, pos)
            stop = pos + 8 + size + (size & 1)
            payload = data[pos + 8:pos + 8 + size]
            if stop > end:
                raise ValueError("Truncated WebP chunk")
        result.append((tag, payload))
        pos = stop
    if kind == "png" and (not result or result[0][0] != b"IHDR" or result[-1] != (b"IEND", b"")):
        raise ValueError("Invalid PNG structure")
    return kind, result


def png_text(tag, payload):
    if tag not in (b"tEXt", b"zTXt", b"iTXt"):
        return None
    key, rest = payload.split(b"\0", 1)
    key = key.decode("latin1")
    if key not in KEYS:
        return None
    if tag == b"zTXt":
        if rest[:1] != b"\0":
            raise ValueError("Unsupported PNG compression")
        rest = zlib.decompress(rest[1:])
    elif tag == b"iTXt":
        flag, method = rest[:2]
        rest = rest[2:].split(b"\0", 2)[2]
        if flag not in (0, 1) or method != 0:
            raise ValueError("Invalid iTXt compression")
        if flag:
            rest = zlib.decompress(rest)
    return key, rest.decode("utf-8")


def tiff(exif):
    data = exif[6:] if exif.startswith(b"Exif\0\0") else exif
    endian = {b"II": "<", b"MM": ">"}.get(data[:2])
    if not endian or len(data) < 8 or struct.unpack_from(endian + "H", data, 2)[0] != 42:
        raise ValueError("Invalid EXIF TIFF header")
    offset = struct.unpack_from(endian + "I", data, 4)[0]
    count = struct.unpack_from(endian + "H", data, offset)[0]
    end = offset + 2 + 12 * count
    if end + 4 > len(data):
        raise ValueError("Truncated EXIF IFD")
    entries = [data[p:p + 12] for p in range(offset + 2, end, 12)]
    return data, endian, entries, data[end:end + 4]


def exif_text(entry, data, endian):
    tag, typ, size = struct.unpack_from(endian + "HHI", entry)
    if typ != 2:
        return None
    offset = struct.unpack_from(endian + "I", entry, 8)[0]
    raw = entry[8:8 + size] if size <= 4 else data[offset:offset + size]
    if len(raw) != size:
        raise ValueError("Truncated EXIF string")
    key, sep, value = raw.rstrip(b"\0").partition(b":")
    if sep and key in (b"prompt", b"workflow"):
        return key.decode(), value.decode("utf-8")
    return None


def extract(kind, items):
    metadata = {}
    for tag, payload in items:
        if kind == "png":
            pair = png_text(tag, payload)
            if pair:
                metadata[pair[0]] = pair[1]
        elif tag == b"EXIF":
            data, endian, entries, _ = tiff(payload)
            for entry in entries:
                pair = exif_text(entry, data, endian)
                if pair:
                    metadata[pair[0]] = pair[1]
    return metadata


def update_exif(original, metadata):
    data, endian, entries, next_ifd = tiff(original or b"II*\0\x08\0\0\0\0\0\0\0\0\0")
    # Append a new IFD: existing nested IFDs and their offsets stay intact.
    output = bytearray(data)
    kept = [e for e in entries if not exif_text(e, data, endian)]
    occupied = {struct.unpack_from(endian + "H", e)[0] for e in kept}
    for key, value in metadata.items():
        tag = 0x0110 if key == "prompt" else 0x010F
        if tag in occupied:
            raise ValueError("Destination EXIF Make/Model tag is occupied; refusing to overwrite unrelated metadata")
        raw = (key + ":" + value).encode("utf-8") + b"\0"
        if len(output) & 1:
            output.append(0)
        offset = len(output)
        output.extend(raw)
        kept.append(struct.pack(endian + "HHI", tag, 2, len(raw)) + (raw.ljust(4, b"\0") if len(raw) <= 4 else struct.pack(endian + "I", offset)))
    if len(output) & 1:
        output.append(0)
    struct.pack_into(endian + "I", output, 4, len(output))
    kept.sort(key=lambda e: struct.unpack_from(endian + "H", e)[0])
    output.extend(struct.pack(endian + "H", len(kept)) + b"".join(kept) + next_ifd)
    return bytes(output)


def rewrite(kind, items, metadata):
    if kind == "png":
        items = [(t, p) for t, p in items if not png_text(t, p)]
        additions = []
        for key, value in metadata.items():
            # ComfyUI reads UTF-8 JSON from tEXt; escape Unicode for PNG Latin-1 compatibility.
            value = json.dumps(json.loads(value), ensure_ascii=True).encode("ascii")
            additions.append((b"tEXt", key.encode() + b"\0" + value))
        items[-1:-1] = additions
        return PNG + b"".join(struct.pack(">I", len(p)) + t + p + struct.pack(">I", zlib.crc32(t + p)) for t, p in items)
    exifs = [p for t, p in items if t == b"EXIF"]
    if len(exifs) > 1:
        raise ValueError("Multiple EXIF chunks are unsupported")
    exif = update_exif(exifs[0] if exifs else None, metadata)
    items = [(t, p) for t, p in items if t != b"EXIF"]
    if items and items[0][0] == b"VP8X":
        p = items[0][1]
        if len(p) != 10:
            raise ValueError("Invalid VP8X")
        items[0] = (b"VP8X", bytes([p[0] | 8]) + p[1:])
    else:
        image = next(((t, p) for t, p in items if t in (b"VP8 ", b"VP8L")), None)
        if not image:
            raise ValueError("WebP image chunk missing")
        tag, p = image
        if tag == b"VP8L" and len(p) >= 5 and p[0] == 0x2f:
            bits = int.from_bytes(p[1:5], "little")
            width, height, alpha = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1, bool(bits & (1 << 28))
        elif tag == b"VP8 " and len(p) >= 10 and p[3:6] == b"\x9d\x01\x2a":
            width, height = (v & 0x3fff for v in struct.unpack_from("<HH", p, 6))
            alpha = any(t == b"ALPH" for t, _ in items)
        else:
            raise ValueError("Invalid WebP bitstream header")
        flags = 8 | (16 if alpha else 0) | (32 if any(t == b"ICCP" for t, _ in items) else 0) | (4 if any(t == b"XMP " for t, _ in items) else 0)
        items.insert(0, (b"VP8X", bytes([flags, 0, 0, 0]) + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")))
    index = next((i for i, (t, _) in enumerate(items) if t == b"XMP "), len(items))
    items.insert(index, (b"EXIF", exif))
    body = b"WEBP" + b"".join(t + struct.pack("<I", len(p)) + p + (b"\0" if len(p) & 1 else b"") for t, p in items)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    temporary = None
    try:
        if not args.source.is_file() or not args.destination.is_file():
            raise ValueError("Source and destination must both be existing files")
        if os.path.samefile(args.source, args.destination):
            raise ValueError("Source and destination must be different files")
        kind, items = chunks(args.source.read_bytes())
        metadata = extract(kind, items)
        if not metadata:
            raise ValueError("Source contains no ComfyUI prompt/workflow metadata")
        target = args.destination.resolve()
        kind, items = chunks(target.read_bytes())
        output = rewrite(kind, items, metadata)
        if {k: json.loads(v) for k, v in extract(*chunks(output)).items()} != {k: json.loads(v) for k, v in metadata.items()}:
            raise ValueError("Metadata verification failed")
        fd, temporary = tempfile.mkstemp(prefix=".metacopy-", dir=target.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, target.stat().st_mode)
        os.replace(temporary, target)
        print("Copied " + ", ".join(sorted(metadata)) + " -> " + str(args.destination))
        return 0
    except (OSError, ValueError, struct.error, zlib.error, IndexError) as error:
        print(f"metacopy: {error}", file=sys.stderr)
        return 1
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    sys.exit(main())
