"""HDR Color Picker entrypoint; every enable constructs one explicit App."""


def registered_session():
    """Recover only this product's actual registration, including after reload."""
    import bpy
    cls = bpy.types.PropertyGroup.bl_rna_get_subclass_py('HDRPickerSettings', None)
    if cls is None:
        return None
    if cls.__module__ != __name__ + '.ui':
        raise RuntimeError('HDR picker registration belongs to a different package')
    session = getattr(cls, '_invariant_picker_session', None)
    if session is None:
        raise RuntimeError('HDR picker registration lost its original App lifecycle')
    return session


def register(*, machines=None, ownership_machine=None):
    previous = registered_session()
    if previous is not None:
        previous.close()
        if not previous.closed or not previous.app.closed:
            raise RuntimeError('Previous picker lifecycle has not reached terminal cleanup')
    if machines is None or ownership_machine is None:
        from .machines import create_machines
        machines, ownership_machine = create_machines()
    from .services import create_app
    from .session import Session
    session = Session(create_app(machines, ownership_machine))
    session.register()


def unregister():
    session = registered_session()
    if session is not None:
        session.close()
