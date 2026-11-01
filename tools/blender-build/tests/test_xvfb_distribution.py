"""The native GUI fixture must relocate without depending on host installation."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from blender_build.unpack_xvfb import unpack


def archive(path, files):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w:xz') as stream:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            stream.addfile(member, io.BytesIO(data))
    data = payload.getvalue()
    header = (f'{"data.tar.xz/":<16}{0:<12}{0:<6}{0:<6}'
              f'{"100644":<8}{len(data):<10}`\n').encode('ascii')
    path.write_bytes(b'!<arch>\n' + header + data + (b'\n' if len(data) % 2 else b''))


class XvfbDistributionTests(unittest.TestCase):
    def test_merged_fixture_preserves_layout_and_relocates_only_compiler_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server, compiler = root / 'server.deb', root / 'compiler.deb'
            binary = b'ELF-prefix\0/usr/bin\0ELF-suffix\0'
            archive(server, {'usr/bin/Xvfb': binary})
            archive(compiler, {'usr/bin/xkbcomp': b'compiler'})
            output = root / 'out'
            unpack([server, compiler], output)
            relocated = (output / 'usr/bin/Xvfb').read_bytes()
            self.assertEqual(relocated, b'ELF-prefix\0usr/bin\0\0ELF-suffix\0')
            self.assertEqual(len(relocated), len(binary))
            for name in ('Xvfb', 'xkbcomp'):
                self.assertTrue((output / 'usr/bin' / name).stat().st_mode & 0o111)

    def test_changed_binary_cannot_be_silently_relocated(self):
        for binary in (b'no embedded path', b'/usr/bin\0/usr/bin\0'):
            with self.subTest(binary=binary), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / 'server.deb'
                archive(source, {'usr/bin/Xvfb': binary, 'usr/bin/xkbcomp': b'compiler'})
                with self.assertRaisesRegex(ValueError, 'relocation no longer matches'):
                    unpack([source], root / 'out')

    def test_truncated_archive_fails_before_extracting_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'server.deb'
            archive(source, {'usr/bin/Xvfb': b'/usr/bin\0'})
            source.write_bytes(source.read_bytes()[:-20])
            with self.assertRaisesRegex(ValueError, 'Truncated Debian archive'):
                unpack([source], root / 'out')
            self.assertFalse((root / 'out/usr/bin/Xvfb').exists())

    def test_payload_cannot_escape_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'server.deb'
            archive(source, {'../outside': b'escape'})
            with self.assertRaises(tarfile.OutsideDestinationError):
                unpack([source], root / 'out')
            self.assertFalse((root / 'outside').exists())
