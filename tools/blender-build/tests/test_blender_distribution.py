"""Pinned distribution extraction preserves the app and releases owned mounts."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tarfile
import tempfile
import unittest
import subprocess

from blender_build import unpack_blender


class DistributionTests(unittest.TestCase):
    def test_linux_distribution_preserves_executable_and_relative_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'blender-5.3.0';source.mkdir()
            binary=source/'blender';binary.write_text('native');binary.chmod(0o755)
            (source/'link').symlink_to('blender')
            archive=root/'blender.tar.xz'
            with tarfile.open(archive,'w:xz') as target:target.add(source,arcname=source.name)
            output=root/'output';unpack_blender.unpack(archive,output)
            self.assertEqual((output/'blender').read_text(),'native')
            self.assertTrue((output/'blender').stat().st_mode&0o111)
            self.assertTrue((output/'link').is_symlink())

    def test_macos_distribution_detaches_on_success_and_copy_failure(self):
        for fail,timeout in ((False,False),(True,False),(False,True)):
            with self.subTest(fail=fail,timeout=timeout),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);archive=root/'blender.dmg';archive.touch();output=root/'output'
                commands=[]
                def command(args,**_kwargs):
                    commands.append(args)
                    if args[1]=='attach':
                        mount=Path(args[args.index('-mountpoint')+1])
                        binary=mount/'Blender.app/Contents/MacOS/Blender'
                        binary.parent.mkdir(parents=True);binary.write_text('native');binary.chmod(0o755)
                        (binary.parent/'alias').symlink_to('Blender')
                    elif timeout and '-force' not in args:
                        raise subprocess.TimeoutExpired(args,60)
                    return SimpleNamespace(returncode=0)
                with patch.object(unpack_blender.sys,'platform','darwin'), \
                     patch.object(unpack_blender.subprocess,'run',side_effect=command):
                    if fail:
                        with patch.object(unpack_blender.shutil,'copytree',side_effect=OSError('copy failed')):
                            with self.assertRaisesRegex(OSError,'copy failed'):unpack_blender.unpack(archive,output)
                    else:
                        unpack_blender.unpack(archive,output)
                        self.assertEqual((output/'Blender.app/Contents/MacOS/Blender').read_text(),'native')
                        self.assertTrue((output/'Blender.app/Contents/MacOS/alias').is_symlink())
                self.assertEqual([command[1] for command in commands],['attach','detach']+(['detach'] if timeout else []))
                self.assertIn('-readonly',commands[0])
                self.assertEqual(commands[1][-1],commands[0][commands[0].index('-mountpoint')+1])

    def test_macos_artifact_cannot_silently_use_another_host(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(unpack_blender.sys,'platform','linux'):
            with self.assertRaisesRegex(RuntimeError,'macOS build host'):
                unpack_blender.unpack(Path(directory)/'blender.dmg',Path(directory)/'out')

    def test_attach_timeout_still_detaches_owned_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);commands=[]
            def command(args,**_kwargs):
                commands.append(args)
                if args[1]=='attach':
                    mount=Path(args[args.index('-mountpoint')+1])
                    (mount/'mounted').touch()
                    raise subprocess.TimeoutExpired(args,120)
                return SimpleNamespace(returncode=0)
            with patch.object(unpack_blender.sys,'platform','darwin'), \
                 patch.object(unpack_blender.subprocess,'run',side_effect=command):
                with self.assertRaises(subprocess.TimeoutExpired):
                    unpack_blender.unpack(root/'blender.dmg',root/'out')
            self.assertEqual([command[1] for command in commands],['attach','detach'])
            self.assertFalse(Path(commands[1][-1]).exists())

    def test_failed_attach_keeps_original_error_when_nothing_was_mounted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);original=RuntimeError('attach failed')
            with patch.object(unpack_blender.sys,'platform','darwin'), \
                 patch.object(unpack_blender.subprocess,'run',side_effect=[original,
                     SimpleNamespace(returncode=1),RuntimeError('nothing mounted')]):
                with self.assertRaisesRegex(RuntimeError,'attach failed') as caught:
                    unpack_blender.unpack(root/'blender.dmg',root/'out')
            self.assertIs(caught.exception,original)
