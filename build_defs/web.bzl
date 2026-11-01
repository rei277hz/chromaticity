"""Public default-file output for a generated static website."""

def _site_impl(ctx):
    output = ctx.attrs.bundle[DefaultInfo].default_outputs[0]
    return [DefaultInfo(default_output = output.project("hdr-color-picker-web.zip"), sub_targets = {
        "directory": [DefaultInfo(default_output = output.project("site"))],
        "manifest": [DefaultInfo(default_output = output.project("manifest.json"))],
    })]

static_site = rule(impl = _site_impl, attrs = {"bundle": attrs.dep()})
