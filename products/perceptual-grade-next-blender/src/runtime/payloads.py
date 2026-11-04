"""JSON values plus bounded NumPy sidecars for helper input and receipts."""

import math
from pathlib import Path
import uuid

import numpy as np


class PayloadStore:
    def __init__(self, directory, *, maximum_bytes=256 * 1024 * 1024):
        self.directory = Path(directory)
        self.maximum_bytes = maximum_bytes
        self.owned = set()

    def encode(self, value, *, prefix):
        files = []

        def visit(item):
            if isinstance(item, np.ndarray):
                if item.dtype.hasobject or item.dtype.kind not in "bifu":
                    raise TypeError("Helper arrays must use numerical dtypes")
                if item.nbytes > self.maximum_bytes or self.bytes + item.nbytes > self.maximum_bytes:
                    raise MemoryError("Helper payload budget exceeded")
                name = f"array-{prefix}-{uuid.uuid4().hex}.npy"
                path = self.directory / name
                self.owned.add(path)
                mapped = np.lib.format.open_memmap(
                    path, mode="w+", dtype=item.dtype, shape=item.shape
                )
                try:
                    mapped[...] = item
                    mapped.flush()
                finally:
                    mapped._mmap.close()
                files.append(name)
                return {"$array": name, "shape": list(item.shape),
                        "dtype": item.dtype.str, "bytes": item.nbytes}
            if isinstance(item, np.generic):
                return visit(item.item())
            if item is None or isinstance(item, (bool, str, int)):
                return item
            if isinstance(item, float):
                return item if math.isfinite(item) else {"$float": repr(item)}
            if isinstance(item, tuple):
                return {"$tuple": [visit(part) for part in item]}
            if isinstance(item, list):
                return [visit(part) for part in item]
            if isinstance(item, dict):
                return {"$dict": [[visit(key), visit(part)] for key, part in item.items()]}
            raise TypeError("Unsupported helper payload: " + type(item).__name__)

        try:
            return visit(value), files
        except BaseException:
            self.release(files)
            raise

    def decode(self, value, *, copy=False):
        if isinstance(value, list):
            return [self.decode(item, copy=copy) for item in value]
        if not isinstance(value, dict):
            return value
        if "$array" in value:
            name = value["$array"]
            if (not isinstance(name, str) or Path(name).name != name
                    or not name.startswith("array-") or not name.endswith(".npy")):
                raise ValueError("Invalid helper array path")
            path = self.directory / name
            if path.is_symlink():
                raise ValueError("Helper array symlinks are not allowed")
            dtype = np.dtype(value["dtype"])
            shape = tuple(value["shape"])
            if (dtype.hasobject or dtype.kind not in "bifu"
                    or any(type(size) is not int or size < 0 for size in shape)):
                raise ValueError("Invalid helper array descriptor")
            size = math.prod(shape) * dtype.itemsize
            if size != value["bytes"] or size > self.maximum_bytes:
                raise ValueError("Helper array size does not match its descriptor")
            array = np.load(path, mmap_mode="r", allow_pickle=False)
            if array.dtype != dtype or array.shape != shape or array.nbytes != size:
                array._mmap.close()
                raise ValueError("Helper array does not match its descriptor")
            if copy:
                result = np.array(array, copy=True)
                array._mmap.close()
                result.flags.writeable = False
                return result
            array.flags.writeable = False
            return array
        if "$tuple" in value:
            return tuple(self.decode(item, copy=copy) for item in value["$tuple"])
        if "$dict" in value:
            return {self.decode(key, copy=copy): self.decode(item, copy=copy)
                    for key, item in value["$dict"]}
        if "$float" in value and value["$float"] in ("nan", "inf", "-inf"):
            return float(value["$float"])
        raise ValueError("Invalid helper payload record")

    @property
    def bytes(self):
        total = 0
        for path in self.directory.glob("array-*.npy"):
            try:
                total += path.stat().st_size
            except FileNotFoundError:
                pass
        return total

    def release(self, names):
        for name in names:
            if Path(name).name != name or not name.startswith("array-"):
                raise ValueError("Invalid helper-owned array path")
            path = self.directory / name
            try:
                path.unlink(missing_ok=True)
                self.owned.discard(path)
            except OSError:
                pass

    def transfer(self, names):
        for name in names:
            if Path(name).name != name or not name.startswith("array-"):
                raise ValueError("Invalid helper-owned array path")
            self.owned.discard(self.directory / name)

    def close(self):
        self.release([path.name for path in tuple(self.owned)])
