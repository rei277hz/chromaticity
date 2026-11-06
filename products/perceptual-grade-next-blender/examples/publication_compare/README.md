# Grade Publication Compare

This extension provides matching Exposure nodes for Shader and Compositor trees.
The **Versioned** nodes publish a packed, immutable helper image and replace its
binding after staging. The **Original** nodes update one helper image in place
and restore its pixel and metadata snapshot if publication fails. The **Banked**
nodes keep two helper images bound and switch a private selector after staging
the inactive image.

All node variants use a single Exposure slider in the Node Editor sidebar. The
slider scales linear RGB by `2^Exposure`. Compositor nodes preserve alpha in the
Color socket; Shader nodes expose a separate Alpha input and output for the
shader host's scalar alpha path. Add nodes from the Color category in either
editor, select a node, and adjust Exposure in the Publication panel.

The publication adapters consume source-bound policies verified by the
invariant framework. The example is intended for inspecting and comparing
publication behavior; it does not include the full Grade color transform.

To capture a comparison session, use F3 in Blender and run **Publication
Compare: Start Drag Trace** before moving the Exposure slider. Run **Publication
Compare: Stop Drag Trace** to flush and close the recording. Unregistering the
extension also closes an active recording. Blender reports the saved JSONL path
in its status message and console; the default directory is
`~/perceptual-grade-publication-compare-logs`.

The trace records Exposure callbacks, publication stages and receipts, pending
and current status changes, errors, and Blender build and source hashes. It
does not record raw pointer coordinates or image contents. The capture is
observational: it does not change publication policy or perform publication
effects.
