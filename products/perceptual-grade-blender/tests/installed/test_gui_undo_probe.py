"""Two real GUI cycles for diagnosing the full installed undo acceptance."""
from . import test_gui_undo as acceptance


class NativeGUIUndoProbeTests(acceptance.NativeGUIUndoTests):
    cycles = 2
