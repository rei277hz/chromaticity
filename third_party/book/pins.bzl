"""Pinned handbook CDN resources and downloadable teaching assets.

mdBook is built from the central Rust dependency graph.
"""

DOC_TOOLS = {
    "mdbook": {
        "version": "0.5.4",
        "license": {
            "url": "https://raw.githubusercontent.com/rust-lang/mdBook/v0.5.4/LICENSE",
            "sha256": "af175b9d96ee93c21a036152e1b905b0b95304d4ae8c2c921c7609100ba8df7e",
            "out": "mdbook-LICENSE",
        },
    },
    "katex": {
        "version": "0.19.0",
        "license": {
            "url": "https://raw.githubusercontent.com/KaTeX/KaTeX/v0.19.0/LICENSE",
            "sha256": "766ccc1f306c885aa45542a9846bbd0a505b27a0374f146778171c2254ce18e3",
            "out": "katex-LICENSE",
        },
        "stylesheet": {
            "url": "https://cdn.jsdelivr.net/npm/katex@0.19.0/dist/katex.min.css",
            "sha256": "d4ab5b8ee16989b070cdb0ea24bd6ad48fc8df1b787f280f29d3ae4f959f2c00",
            "out": "katex.min.css",
        },
        "script": {
            "url": "https://cdn.jsdelivr.net/npm/katex@0.19.0/dist/katex.min.js",
            "sha256": "103a53763cc033bba8d175bf3f0ba597c3505c9b6747dd3f2c7bc2a6bfcc8ae7",
            "out": "katex.min.js",
        },
    },
}

TUTORIAL_ASSETS = {
    "colorchecker2014": {
        "commit": "50ce963b5220363be1a13a006e3720f12fbddddf",
        "url": "https://raw.githubusercontent.com/colour-science/colour-nuke/50ce963b5220363be1a13a006e3720f12fbddddf/colour_nuke/resources/images/ColorChecker2014/ACEScg_ColorChecker2014.exr",
        "sha256": "2d40f40e638fd0ad07c92c9c530fc50fea534d7c7c0b510bcb2b98d154534103",
        "out": "ACEScg_ColorChecker2014.exr",
    },
    "colour_nuke_license": {
        "url": "https://raw.githubusercontent.com/colour-science/colour-nuke/50ce963b5220363be1a13a006e3720f12fbddddf/LICENSE",
        "sha256": "ed4e6059c5963ed21861b9b7d2eb830829eab9bcc50dea3a557d87a31e228712",
        "out": "colour-nuke-LICENSE",
    },
}

DOC_FONTS = {
    "pontano-sans": {
        "family": "Pontano Sans",
        "version": "5.3.0",
        "weights": "300 700",
        "normal": {
            "url": "https://cdn.jsdelivr.net/npm/@fontsource-variable/pontano-sans@5.3.0/files/pontano-sans-latin-wght-normal.woff2",
            "sha256": "9ce17b0d450bdd4e14bb325afad8344e2ded081abb6b72831ee5580649cff6bb",
            "out": "pontano-sans.woff2",
        },
        "license": {
            "url": "https://cdn.jsdelivr.net/npm/@fontsource-variable/pontano-sans@5.3.0/LICENSE",
            "sha256": "8ba38df62c6f6fd4504faa77242ba47360430ad4f6f51be395799c89e0212a0e",
            "out": "pontano-sans-OFL.txt",
        },
    },
    "roboto-mono": {
        "family": "Roboto Mono",
        "version": "5.3.0",
        "weights": "100 700",
        "normal": {
            "url": "https://cdn.jsdelivr.net/npm/@fontsource-variable/roboto-mono@5.3.0/files/roboto-mono-latin-wght-normal.woff2",
            "sha256": "b81cd55177300649be8f95b3b747d721ce607e8ed2856e25bd0c630cfd631faf",
            "out": "roboto-mono.woff2",
        },
        "license": {
            "url": "https://cdn.jsdelivr.net/npm/@fontsource-variable/roboto-mono@5.3.0/LICENSE",
            "sha256": "b489132782690f2cc1ed23ab56d7057bbb08c42573603e8e704ae2e2ea9c8216",
            "out": "roboto-mono-OFL.txt",
        },
    },
}
