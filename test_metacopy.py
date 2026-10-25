"""Container-level tests; no image codec or third-party packages needed."""
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

import metacopy as m


def png():
    def chunk(tag, payload):
        return struct.pack('>I', len(payload)) + tag + payload + struct.pack('>I', zlib.crc32(tag + payload))
    return m.PNG + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0')) + chunk(b'IEND', b'')


def webp():
    # Minimal VP8L header fixture for container manipulation, not codec decoding.
    p = b'\x2f\0\0\0\0'
    body = b'WEBPVP8L' + struct.pack('<I', len(p)) + p + b'\0'
    return b'RIFF' + struct.pack('<I', len(body)) + body


class CopyTests(unittest.TestCase):
    metadata = {'prompt': json.dumps({'text': '日本語 😀'}), 'workflow': '{"nodes": []}'}

    def test_all_format_pairs_and_image_payloads(self):
        for source in (png(), webp()):
            for target in (png(), webp()):
                with self.subTest(source=source[:4], target=target[:4]), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
                    a, b = Path(folder) / 'source', Path(folder) / 'target'
                    a.write_bytes(m.rewrite(*m.chunks(source), self.metadata))
                    b.write_bytes(m.rewrite(*m.chunks(target), {'prompt': '{}', 'workflow': '{}'}))
                    before = a.read_bytes()
                    with patch('sys.argv', ['metacopy', str(a), str(b)]), contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(m.main(), 0)
                    self.assertEqual(a.read_bytes(), before)
                    got = m.extract(*m.chunks(b.read_bytes()))
                    self.assertEqual({k: json.loads(v) for k, v in got.items()}, {k: json.loads(v) for k, v in self.metadata.items()})
                    image_tags = {b'IDAT', b'VP8L'}
                    self.assertEqual([x for x in m.chunks(target)[1] if x[0] in image_tags], [x for x in m.chunks(b.read_bytes())[1] if x[0] in image_tags])

    def test_missing_destination_and_missing_metadata(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            a, b = Path(folder) / 'a', Path(folder) / 'b'
            a.write_bytes(png())
            with patch('sys.argv', ['metacopy', str(a), str(b)]), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(m.main(), 1)
            self.assertFalse(b.exists())
            b.write_bytes(webp())
            with patch('sys.argv', ['metacopy', str(a), str(b)]), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(m.main(), 1)
            self.assertEqual(b.read_bytes(), webp())

    def test_png_compressed_text(self):
        value = self.metadata['prompt'].encode()
        self.assertEqual(m.png_text(b'zTXt', b'prompt\0\0' + zlib.compress(value)), ('prompt', value.decode()))
        self.assertEqual(m.png_text(b'iTXt', b'prompt\0\1\0\0\0' + zlib.compress(value)), ('prompt', value.decode()))

    def test_exif_preserves_other_tags_and_big_endian(self):
        for endian, mark in [('<', b'II'), ('>', b'MM')]:
            original = mark + struct.pack(endian + 'HIH', 42, 8, 1) + struct.pack(endian + 'HHI', 274, 3, 1) + struct.pack(endian + 'H', 6) + b'\0\0' + b'\0' * 4
            result = m.update_exif(b'Exif\0\0' + original, self.metadata)
            _, _, entries, _ = m.tiff(result)
            self.assertIn(original[10:22], entries)
            self.assertEqual(m.extract('webp', [(b'EXIF', result)]), self.metadata)


if __name__ == '__main__':
    unittest.main()
