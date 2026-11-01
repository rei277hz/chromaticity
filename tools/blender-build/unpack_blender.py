"""Extract the pinned standalone Blender distribution as a Buck artifact."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


def unpack_macos(archive,destination):
    if sys.platform!='darwin':raise RuntimeError('The pinned macOS distribution requires a macOS build host')
    directory=Path(tempfile.mkdtemp(prefix='pg-blender-dmg-'))
    mount=directory/'volume';mount.mkdir()
    original_error=None;detached=False
    try:
        subprocess.run(['/usr/bin/hdiutil','attach','-readonly','-nobrowse','-noautoopen',
            '-mountpoint',str(mount),str(archive.resolve())],check=True,capture_output=True,timeout=120)
        app=mount/'Blender.app'
        if not (app/'Contents/MacOS/Blender').is_file():
            raise ValueError('Blender DMG has no native app executable')
        shutil.copytree(app,destination/'Blender.app',symlinks=True)
    except BaseException as error:
        original_error=error
        raise
    finally:
        # Attach may mount the image before timing out or reporting an error.
        # Always try our exact mountpoint, preserving the original failure.
        try:
            try:
                result=subprocess.run(['/usr/bin/hdiutil','detach',str(mount)],capture_output=True,timeout=60)
                detached=result.returncode==0
            except (OSError,subprocess.TimeoutExpired):
                detached=False
            if not detached:
                subprocess.run(['/usr/bin/hdiutil','detach','-force',str(mount)],
                    check=True,capture_output=True,timeout=60)
                detached=True
        except BaseException as cleanup_error:
            if original_error is None:raise
            original_error.add_note('Could not detach owned Blender mount: '+str(cleanup_error))
        finally:
            if detached:
                shutil.rmtree(directory)
            else:
                # Do not recursively traverse a possibly still-mounted image.
                for path in (mount,directory):
                    try:path.rmdir()
                    except OSError:pass


def unpack(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    if archive.suffix=='.dmg':
        unpack_macos(archive,destination)
        return
    staging = destination / '.unpack'
    staging.mkdir()
    with tarfile.open(archive, 'r:xz') as source:
        source.extractall(staging, filter='data')
    roots = list(staging.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ValueError('Blender archive must have one enclosing directory')
    if not (roots[0] / 'blender').is_file():
        raise ValueError('Blender archive has no native executable')
    for item in roots[0].iterdir():
        shutil.move(item, destination / item.name)
    shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    unpack(args.archive, args.output_dir)


if __name__ == '__main__':
    main()
