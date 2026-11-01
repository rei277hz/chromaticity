# Official channel-rust-1.99.1.toml, released 2026-10-15.
# Existing Linux compiler, Cargo, and std pins are unchanged from the web toolchain.
RUST_VERSION = "1.99.1"
RUST_DIST = "https://static.rust-lang.org/dist/2026-10-15/"

ARCHIVES = {
    "rustc_archive_linux_x86_64": ("rustc-1.99.1-x86_64-unknown-linux-gnu.tar.xz", "2ff05ff9c08a90861e7f6e4065b40a8b87463b4576186fd613871c3e37f2091f"),
    "cargo_archive_linux_x86_64": ("cargo-1.99.1-x86_64-unknown-linux-gnu.tar.xz", "53f3521949404d595efb06a55c12c5658d4ed1c75566f33d3d514eaebe70bd8a"),
    "clippy_archive_linux_x86_64": ("clippy-1.99.1-x86_64-unknown-linux-gnu.tar.xz", "458339712a058e52cc4522ff9ef8b59cd1ea1340312216cd94194c464a3f6dc5"),
    "host_std_archive_linux_x86_64": ("rust-std-1.99.1-x86_64-unknown-linux-gnu.tar.xz", "109b074225bf5b9ea3820890876bfdf4ed161adbfaf94b2b4b5984c85ee5d958"),
    "rustc_archive_darwin_arm64": ("rustc-1.99.1-aarch64-apple-darwin.tar.xz", "23948a0a9c162fd2952defb3fb0462c44e8fcfd1a4ab8a274a1e1bdb2cf810a3"),
    "cargo_archive_darwin_arm64": ("cargo-1.99.1-aarch64-apple-darwin.tar.xz", "685e563d94db1f003ffa5f5831439eec02569b9950b69867953c8213269c1eaf"),
    "clippy_archive_darwin_arm64": ("clippy-1.99.1-aarch64-apple-darwin.tar.xz", "c463f31831196702fc544900a0dc4c1837905327507fbec751fe46e59ca098bf"),
    "host_std_archive_darwin_arm64": ("rust-std-1.99.1-aarch64-apple-darwin.tar.xz", "fe79d6ab5a0321de26463999d8c112b8ad3eafbcbcf822d66a2300b45dde1031"),
    "wasm_std_archive": ("rust-std-1.99.1-wasm32-unknown-unknown.tar.xz", "5f628f857dd00a8aa3fcac2e275665d2782066a5795274ed124c5b560f46423c"),
}
