"""Start the packaged helper under an isolated, non-registering namespace."""

from importlib import import_module
from importlib.machinery import ModuleSpec
import json
from pathlib import Path
import sys
from types import ModuleType


def main():
    config = json.loads(Path(sys.argv[-1]).read_text(encoding="utf8"))
    namespace = "_grade_helper_" + config["session"]
    package = ModuleType(namespace)
    package.__path__ = [config["package"]]
    package.__package__ = namespace
    package.__spec__ = ModuleSpec(namespace, loader=None, is_package=True)
    package.__spec__.submodule_search_locations = package.__path__
    sys.modules[namespace] = package
    import_module(namespace + ".runtime.worker").run(config, namespace)


if __name__ == "__main__":
    main()
