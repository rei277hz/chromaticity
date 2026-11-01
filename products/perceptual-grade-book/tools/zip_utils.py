"""Original deterministic archive helpers, isolated from extension packaging."""
import hashlib
from pathlib import Path
import zipfile

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def files(tree):
    if not tree.is_dir():raise ValueError(f'Missing required input directory: {tree}')
    return {p.relative_to(tree).as_posix():p for p in sorted(tree.rglob('*')) if p.is_file()}

def write_zip(destination,entries):
    # Publish only a closed, complete archive. An interrupted writer must not
    # leave a truncated ZIP at the declared output path.
    import tempfile
    destination=Path(destination)
    with tempfile.TemporaryDirectory(prefix='pg-archive-',dir=destination.parent) as temporary:
        staged=Path(temporary)/destination.name
        with zipfile.ZipFile(staged,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for name,path in sorted(entries.items()):
                info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
                info.compress_type=zipfile.ZIP_DEFLATED
                info.create_system=3
                info.external_attr=0o100644<<16
                archive.writestr(info,path.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
        with zipfile.ZipFile(staged) as archive:
            if archive.namelist()!=sorted(entries) or archive.testzip() is not None:
                raise ValueError('Generated archive is incomplete or corrupt')
        staged.replace(destination)
