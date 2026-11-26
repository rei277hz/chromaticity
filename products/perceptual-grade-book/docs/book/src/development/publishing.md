# Publishing

The book product builds one static site containing the English and Simplified
Chinese User Manual and the English Technical Report. It also builds a
deterministic ZIP archive with fixed file ordering and timestamps. Build the
site and publication archive with Buck2 remote execution:

```sh
buck2 build --remote-only '//products/perceptual-grade-book:site[html]' --show-output
buck2 build --remote-only '//products/perceptual-grade-book:archive[zip]' --show-output
```

The print targets produce manual PDFs and EPUBs for both languages and English
Technical Report PDF and EPUB outputs. Print exports are derived from the same
authored Markdown and do not replace the website files. The book product README
lists every supported output and build command.

To update the local website checkout, run:

```sh
buck2 run --remote-only //products/perceptual-grade-book:publish
```

The publisher validates the complete site archive before replacing the contents
of the configured book-site directory. It preserves the parent website
checkout's `.git` directory and sibling content. Committing and pushing that
checkout are separate operations.

The User Manual includes one archived extension ZIP. Assembly verifies its
published bytes against the checked-in SHA256 manifest. Do not regenerate,
repackage, or substitute that archive as part of publishing.
