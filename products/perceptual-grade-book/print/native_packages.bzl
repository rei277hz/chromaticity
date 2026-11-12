# Debian 13 amd64 runtime closure for WeasyPrint's Pango/Fontconfig backend.
NATIVE_PACKAGES = {
    "fontconfig_config": {
        "filename": "fontconfig-config_2.15.0-2.3_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/f/fontconfig/fontconfig-config_2.15.0-2.3_amd64.deb",
        "sha256": "0475c00d02660c07a15085051818625331bb502e053242106aaaa1f2ddb41225",
    },
    "libatomic1": {
        "filename": "libatomic1_14.2.0-19_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/g/gcc-14/libatomic1_14.2.0-19_amd64.deb",
        "sha256": "212b399aae2f7299203d261a57e49372e09565a9a5ea971905f94a3960366c05",
    },
    "libblkid1": {
        "filename": "libblkid1_2.41.5-0+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/u/util-linux/libblkid1_2.41.5-0+deb13u1_amd64.deb",
        "sha256": "81535f3c2c0efc732965907c8749103a0a26377c761622c9ce39b4c92dcde52f",
    },
    "libbrotli1": {
        "filename": "libbrotli1_1.1.0-2+b7_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/b/brotli/libbrotli1_1.1.0-2+b7_amd64.deb",
        "sha256": "0fb79f88db210afbd69282ab9649e525f393ec6950ca34da1a6b359250b8d7db",
    },
    "libbz2": {
        "filename": "libbz2-1.0_1.0.8-6_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/b/bzip2/libbz2-1.0_1.0.8-6_amd64.deb",
        "sha256": "cba4cda04244b5e481bb15524bc3c983a7d1b6f330013b9b381706a2fcb65310",
    },
    "libdatrie1": {
        "filename": "libdatrie1_0.2.13-3+b1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libd/libdatrie/libdatrie1_0.2.13-3+b1_amd64.deb",
        "sha256": "339eb88f23d72b8f0b7b1aebcefbab6de600d97b88bc6222dd8aad11d2ca9051",
    },
    "libexpat1": {
        "filename": "libexpat1_2.8.3-1~deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/e/expat/libexpat1_2.8.3-1~deb13u1_amd64.deb",
        "sha256": "38abe0e710a07688e9c149d74536e67cfee0364bdb64dd6d644c32a1cfad389f",
    },
    "libfontconfig1": {
        "filename": "libfontconfig1_2.15.0-2.3_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/f/fontconfig/libfontconfig1_2.15.0-2.3_amd64.deb",
        "sha256": "7ae91ec59857cc8e375eb2bdd371a4a69daea38f7787d06d474a847867d852b1",
    },
    "libffi8": {
        "filename": "libffi8_3.4.8-2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libf/libffi/libffi8_3.4.8-2_amd64.deb",
        "sha256": "0ebdc340de33333639c3c63874cd4b15ac2e83dfa1ef3053b7eefaf4919f4f68",
    },
    "libfreetype6": {
        "filename": "libfreetype6_2.13.3+dfsg-1+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/f/freetype/libfreetype6_2.13.3+dfsg-1+deb13u1_amd64.deb",
        "sha256": "e4947f3291528f03d574f2b01d5c5fc45c58c47480f32888a5cdf0f231ab584e",
    },
    "libfribidi0": {
        "filename": "libfribidi0_1.0.16-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/f/fribidi/libfribidi0_1.0.16-1_amd64.deb",
        "sha256": "f8c35ec8606d0843bd3cf020c6cfa39ddfe717ec58ed826b5855ba9927eb0d55",
    },
    "libglib2": {
        "filename": "libglib2.0-0t64_2.84.4-3~deb13u5_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/g/glib2.0/libglib2.0-0t64_2.84.4-3~deb13u5_amd64.deb",
        "sha256": "e2baf92c57d1db1753e5781a61450d9a01e7833c7bd2dfe87776a6811c11ecc2",
    },
    "libgraphite2": {
        "filename": "libgraphite2-3_1.3.14-2+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/g/graphite2/libgraphite2-3_1.3.14-2+deb13u1_amd64.deb",
        "sha256": "1769ba3ed3c1fc75b7fbe02678e32aa24391205813eceef4e1e3500015d12ee3",
    },
    "libharfbuzz0b": {
        "filename": "libharfbuzz0b_10.2.0-1+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/h/harfbuzz/libharfbuzz0b_10.2.0-1+deb13u1_amd64.deb",
        "sha256": "932165b933e5eb633293afe984a983ebe89cb27c923ce7208626f1da6c0c7941",
    },
    "libharfbuzz_subset": {
        "filename": "libharfbuzz-subset0_10.2.0-1+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/h/harfbuzz/libharfbuzz-subset0_10.2.0-1+deb13u1_amd64.deb",
        "sha256": "2d0de8588408af221927b372c3c8d439d638a0a8abb549660ed5813ab529e6bc",
    },
    "libmount1": {
        "filename": "libmount1_2.41.5-0+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/u/util-linux/libmount1_2.41.5-0+deb13u1_amd64.deb",
        "sha256": "6d00f45f2e80e078e906e3eedecd3ba6913e39fef49bff361ee583f17f00ec05",
    },
    "libpango1": {
        "filename": "libpango-1.0-0_1.56.3-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/p/pango1.0/libpango-1.0-0_1.56.3-1_amd64.deb",
        "sha256": "4fa38472696d2ddb10bfc9a4692a9446e8478fdb1f48c769a609fc9fec3adfc5",
    },
    "libpangoft2": {
        "filename": "libpangoft2-1.0-0_1.56.3-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/p/pango1.0/libpangoft2-1.0-0_1.56.3-1_amd64.deb",
        "sha256": "b506cf66f78ddf542ddb4bb4a68b3d748d41caa6e190e4480430a6630c1e5105",
    },
    "libpcre2": {
        "filename": "libpcre2-8-0_10.46-1~deb13u2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/p/pcre2/libpcre2-8-0_10.46-1~deb13u2_amd64.deb",
        "sha256": "1252b96a5bc44bb5db982bef8eb18e54f5047cede2aff641bce4f8e1edb91c3e",
    },
    "libpixman1": {
        "filename": "libpixman-1-0_0.44.0-3_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/p/pixman/libpixman-1-0_0.44.0-3_amd64.deb",
        "sha256": "3862c87596f6b4b60fc916395fd69aa10af28a875a8e5c081a8cf30ddd120bd6",
    },
    "libpng16": {
        "filename": "libpng16-16t64_1.6.48-1+deb13u5_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libp/libpng1.6/libpng16-16t64_1.6.48-1+deb13u5_amd64.deb",
        "sha256": "2465b4e9fa85cff54dc10a6da3e64074d8d9292c86e4a8f989b809d6b158e97e",
    },
    "libselinux1": {
        "filename": "libselinux1_3.8.1-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libs/libselinux/libselinux1_3.8.1-1_amd64.deb",
        "sha256": "68bb8d32bd8d6d7d2f5952a169db03d1484b46ae1e52abccdec42a19dccea5d5",
    },
    "libthai_data": {
        "filename": "libthai-data_0.1.29-2_all.deb",
        "url": "https://deb.debian.org/debian/pool/main/libt/libthai/libthai-data_0.1.29-2_all.deb",
        "sha256": "fd38d40602834d510a29140bd27fd48485105e834f03dccab1c02e2edaa794dd",
    },
    "libthai0": {
        "filename": "libthai0_0.1.29-2+b1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libt/libthai/libthai0_0.1.29-2+b1_amd64.deb",
        "sha256": "e6364c07aeeffe9a95f267061d9df168e48e9dc9126c3b40e19dc829f67702a7",
    },
    "libuuid1": {
        "filename": "libuuid1_2.41.5-0+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/u/util-linux/libuuid1_2.41.5-0+deb13u1_amd64.deb",
        "sha256": "c1bf4c4c3ff48c57fabf93307dfb56996b60cfa33927afc4158b5db36fb2721e",
    },
    "libzstd1": {
        "filename": "libzstd1_1.5.7+dfsg-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libz/libzstd/libzstd1_1.5.7+dfsg-1_amd64.deb",
        "sha256": "2f6a2aeacfc925eba8b00ac9139bc4bfccf8cacb09eb93de067074b26948eef9",
    },
    "zlib1g": {
        "filename": "zlib1g_1.3.dfsg+really1.3.1-1+b1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/z/zlib/zlib1g_1.3.dfsg+really1.3.1-1+b1_amd64.deb",
        "sha256": "015be740d6236ad114582dea500c1d907f29e16d6db00566ca32fb68d71ac90d",
    },
}
