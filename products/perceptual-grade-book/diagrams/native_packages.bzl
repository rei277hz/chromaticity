# Debian 13 amd64 additions to the book print runtime for headless Chromium.
# Runtime drawing uses CPU only; no Mesa driver or desktop services are needed.
# Pins originate in Debian trixie/main/binary-amd64/Packages.
BROWSER_PACKAGES = {
    "libasound2-data": {
        "filename": "libasound2-data_1.2.14-1+deb13u1_all.deb",
        "url": "https://deb.debian.org/debian/pool/main/a/alsa-lib/libasound2-data_1.2.14-1+deb13u1_all.deb",
        "sha256": "04688afdff3769c0f685541daed7b2f6f0cb946799ddf1d5847ddf11fe245559"
    },
    "libasound2t64": {
        "filename": "libasound2t64_1.2.14-1+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/a/alsa-lib/libasound2t64_1.2.14-1+deb13u1_amd64.deb",
        "sha256": "5495496142d57e5ad6d581ac5456ec3c87f872c109a2bfb815d154b673eebc67"
    },
    "libatk-bridge2.0-0t64": {
        "filename": "libatk-bridge2.0-0t64_2.56.2-1+deb13u2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/a/at-spi2-core/libatk-bridge2.0-0t64_2.56.2-1+deb13u2_amd64.deb",
        "sha256": "c0fe87ea1bdca2f938eaa8286af5ad38ecd15cf18c6cfb5961d7d46ac3192325"
    },
    "libatk1.0-0t64": {
        "filename": "libatk1.0-0t64_2.56.2-1+deb13u2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/a/at-spi2-core/libatk1.0-0t64_2.56.2-1+deb13u2_amd64.deb",
        "sha256": "24786bc90e3ff80c4d1d8bdb5ec18bb5f06df9081a5233eb080f3202fcf6a1c3"
    },
    "libatspi2.0-0t64": {
        "filename": "libatspi2.0-0t64_2.56.2-1+deb13u2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/a/at-spi2-core/libatspi2.0-0t64_2.56.2-1+deb13u2_amd64.deb",
        "sha256": "65e9c9ecbd820fba2d04104cddd0bad33d256cbdfe0d1cb5365f10e363df2315"
    },
    "libavahi-client3": {
        "filename": "libavahi-client3_0.8-16_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/a/avahi/libavahi-client3_0.8-16_amd64.deb",
        "sha256": "27df3f1c0190d13ec6d014c5515c2ec8e9a49d0983f48fc9e5756ee4e62d7e37"
    },
    "libavahi-common-data": {
        "filename": "libavahi-common-data_0.8-16_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/a/avahi/libavahi-common-data_0.8-16_amd64.deb",
        "sha256": "a3c0cb1326ed60cbbef133c31af28759f7a922d886d001a138d52bbf0af908d6"
    },
    "libavahi-common3": {
        "filename": "libavahi-common3_0.8-16_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/a/avahi/libavahi-common3_0.8-16_amd64.deb",
        "sha256": "fb092fc55f1c7f3db0ac64467f30ebae8145543570b8e99f17ce84cf1dd28bb6"
    },
    "libcairo2": {
        "filename": "libcairo2_1.18.4-1+b1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/c/cairo/libcairo2_1.18.4-1+b1_amd64.deb",
        "sha256": "01390b049661e4cc8bd39cef78b41c2587d4035619d3b00d6c7846f43d80bbba"
    },
    "libcom-err2": {
        "filename": "libcom-err2_1.47.2-3+b12_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/e/e2fsprogs/libcom-err2_1.47.2-3+b12_amd64.deb",
        "sha256": "bd43e020b8fed399db3eebf098111f10fba4c436fff99ccad72cc7e27c9764ec"
    },
    "libcups2t64": {
        "filename": "libcups2t64_2.4.10-3+deb13u2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/c/cups/libcups2t64_2.4.10-3+deb13u2_amd64.deb",
        "sha256": "278c57da32afceec1f406869e790b29f40c75b02bb8e512dd903d5a5264df9d2"
    },
    "libdbus-1-3": {
        "filename": "libdbus-1-3_1.16.2-2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/d/dbus/libdbus-1-3_1.16.2-2_amd64.deb",
        "sha256": "bbcb711daff7e104b5f80f9b05475b6142674bfe65518a36a56e96a91068a3f5"
    },
    "libdrm-common": {
        "filename": "libdrm-common_2.4.124-2_all.deb",
        "url": "https://deb.debian.org/debian/pool/main/libd/libdrm/libdrm-common_2.4.124-2_all.deb",
        "sha256": "9a8a6c65c165e9964f106fb4ac710959b5d33e0790227e3ab6b27c4742d1254a"
    },
    "libdrm2": {
        "filename": "libdrm2_2.4.124-2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libd/libdrm/libdrm2_2.4.124-2_amd64.deb",
        "sha256": "fe2276901c7cd7b8079de63072d37fe1cbeb4eb001a3bc1f1d662ad89aa0890e"
    },
    "libgbm1": {
        "filename": "libgbm1_25.0.7-2+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/m/mesa/libgbm1_25.0.7-2+deb13u1_amd64.deb",
        "sha256": "31fb6d76b9ceaf13848fa617df53f85f62626b4fe7464a93811c720af6d5f2dd"
    },
    "libgmp10": {
        "filename": "libgmp10_6.3.0+dfsg-3_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/g/gmp/libgmp10_6.3.0+dfsg-3_amd64.deb",
        "sha256": "d0d0265eb01770f17afd0f7c8c0622f80479dcfbbe13653a0debeec61464e622"
    },
    "libgnutls30t64": {
        "filename": "libgnutls30t64_3.8.9-3+deb13u4_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/g/gnutls28/libgnutls30t64_3.8.9-3+deb13u4_amd64.deb",
        "sha256": "18a8bdfd91c7e3bcb01719d55a2b56849c7160b34f1f52b1c4fdfdd41bf1352b"
    },
    "libgssapi-krb5-2": {
        "filename": "libgssapi-krb5-2_1.21.3-5+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/k/krb5/libgssapi-krb5-2_1.21.3-5+deb13u1_amd64.deb",
        "sha256": "30847c1fde4240567d7ed3aeab4f655dd591203758b857e85e824045aae70299"
    },
    "libhogweed6t64": {
        "filename": "libhogweed6t64_3.10.1-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/n/nettle/libhogweed6t64_3.10.1-1_amd64.deb",
        "sha256": "b059ed155115ac09da295322de48ee1ed58ef5fa45edcc9e12ff0e94636ef25f"
    },
    "libidn2-0": {
        "filename": "libidn2-0_2.3.8-2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libi/libidn2/libidn2-0_2.3.8-2_amd64.deb",
        "sha256": "90b039bcdc4578f8e1c4935adf8dbb525e36a164deefdbbb8c45bac347d48278"
    },
    "libk5crypto3": {
        "filename": "libk5crypto3_1.21.3-5+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/k/krb5/libk5crypto3_1.21.3-5+deb13u1_amd64.deb",
        "sha256": "7da07ee674b47f1f0be7cc89317c25310086a1f1761217d0f72e6ae2c5a69b84"
    },
    "libkeyutils1": {
        "filename": "libkeyutils1_1.6.3-6_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/k/keyutils/libkeyutils1_1.6.3-6_amd64.deb",
        "sha256": "0b11ad17be0300b63ad4eeb4c6450fed24d34b7b740f23e5363dcb29ee6d5eba"
    },
    "libkrb5-3": {
        "filename": "libkrb5-3_1.21.3-5+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/k/krb5/libkrb5-3_1.21.3-5+deb13u1_amd64.deb",
        "sha256": "47d71d6a7f2e59b9bae5f89602397594805113b95889ad18fa703cd53abafc97"
    },
    "libkrb5support0": {
        "filename": "libkrb5support0_1.21.3-5+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/k/krb5/libkrb5support0_1.21.3-5+deb13u1_amd64.deb",
        "sha256": "3a0acd8b37955c0e102c756b52c97df2a31f67b96453c35dab70df218d309117"
    },
    "libnettle8t64": {
        "filename": "libnettle8t64_3.10.1-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/n/nettle/libnettle8t64_3.10.1-1_amd64.deb",
        "sha256": "1b03d4a9cd9c8143ba50fe6396f36937e901a317d492d179f4596862c1731cfe"
    },
    "libnspr4": {
        "filename": "libnspr4_4.36-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/n/nspr/libnspr4_4.36-1_amd64.deb",
        "sha256": "87fc2039ee89cff2b8010fa9535706b1def40031acfc52bf12197dcb3cb7b064"
    },
    "libnss3": {
        "filename": "libnss3_3.110-1+deb13u4_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/n/nss/libnss3_3.110-1+deb13u4_amd64.deb",
        "sha256": "8d20d0754039e15e9bd2c8484e98dc9c2982907d4f20834da29a9501913d00b5"
    },
    "libp11-kit0": {
        "filename": "libp11-kit0_0.25.5-3_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/p/p11-kit/libp11-kit0_0.25.5-3_amd64.deb",
        "sha256": "784bf2063e166c8bc851a32623b74ebd85c499043a9d57c5bbd64fa63447f45a"
    },
    "libsqlite3-0": {
        "filename": "libsqlite3-0_3.46.1-7+deb13u2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/s/sqlite3/libsqlite3-0_3.46.1-7+deb13u2_amd64.deb",
        "sha256": "0a459adaffd901109f7811ab65f58e7a957b4907d05539cf3d1184efdcde0468"
    },
    "libssl3t64": {
        "filename": "libssl3t64_3.5.7-1~deb13u2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/o/openssl/libssl3t64_3.5.7-1~deb13u2_amd64.deb",
        "sha256": "916f7f40b34a06e6ebfaefcdab331bff458328411da672598f126a760472467d"
    },
    "libtasn1-6": {
        "filename": "libtasn1-6_4.20.0-2+deb13u1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libt/libtasn1-6/libtasn1-6_4.20.0-2+deb13u1_amd64.deb",
        "sha256": "23fec6e06583ce2bad9b2c04c9b485e90440e259b1abf8677cd80d3ce60831ad"
    },
    "libunistring5": {
        "filename": "libunistring5_1.3-2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libu/libunistring/libunistring5_1.3-2_amd64.deb",
        "sha256": "6dd3490bef06ea1096f32d10766b7e016cf579bfae8451d1b7df15ce05b8aa46"
    },
    "libwayland-server0": {
        "filename": "libwayland-server0_1.23.1-3_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/w/wayland/libwayland-server0_1.23.1-3_amd64.deb",
        "sha256": "2967212bd582e0dffca443fdc44f4c660e7368d41f7ee3a7f6314e0c3abfe9ea"
    },
    "libx11-6": {
        "filename": "libx11-6_1.8.12-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libx11/libx11-6_1.8.12-1_amd64.deb",
        "sha256": "b5a3fd3bf8c8fd0364bfb9bea00dcba7fc301229bd02dded084632d31f5b0fb3"
    },
    "libx11-data": {
        "filename": "libx11-data_1.8.12-1_all.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libx11/libx11-data_1.8.12-1_all.deb",
        "sha256": "c54f87069888f80ba4da586da6147d74c7598ccdd8b90906dbc4271fa414c738"
    },
    "libxau6": {
        "filename": "libxau6_1.0.11-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxau/libxau6_1.0.11-1_amd64.deb",
        "sha256": "689a9f0e0ba3e2c65431f864871e303ee904de69dd28abfc462663fae030227f"
    },
    "libxcb-render0": {
        "filename": "libxcb-render0_1.17.0-2+b1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxcb/libxcb-render0_1.17.0-2+b1_amd64.deb",
        "sha256": "7f6e36978e0f70a590fbad4042a692c70b50ca7cbcdc53fa7e9d9ab87933acc6"
    },
    "libxcb-shm0": {
        "filename": "libxcb-shm0_1.17.0-2+b1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxcb/libxcb-shm0_1.17.0-2+b1_amd64.deb",
        "sha256": "d1777a813f484e89f3dcaadd1d5f2b1a13e9313b6bf70eded16d8ce743208fef"
    },
    "libxcb1": {
        "filename": "libxcb1_1.17.0-2+b1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxcb/libxcb1_1.17.0-2+b1_amd64.deb",
        "sha256": "5c222a72d11b866447da31693254f738430726e3e065a384e82687b2fd2f978b"
    },
    "libxcomposite1": {
        "filename": "libxcomposite1_0.4.6-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxcomposite/libxcomposite1_0.4.6-1_amd64.deb",
        "sha256": "20e3c1d9b2135f0c8c4246a9fd26a51a57d5850c3b36ecc173c45d6be7328af3"
    },
    "libxdamage1": {
        "filename": "libxdamage1_1.1.6-1+b2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxdamage/libxdamage1_1.1.6-1+b2_amd64.deb",
        "sha256": "e51e43f23f3befbc1f9408271f4df6773d37caece9ce7e1f38abade382f7fbf7"
    },
    "libxdmcp6": {
        "filename": "libxdmcp6_1.1.5-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxdmcp/libxdmcp6_1.1.5-1_amd64.deb",
        "sha256": "0740dc760916b2008b45417a42a8fd7dd5de370fb57d31373f15034cda8acf0b"
    },
    "libxext6": {
        "filename": "libxext6_1.3.4-1+b3_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxext/libxext6_1.3.4-1+b3_amd64.deb",
        "sha256": "fc618ec40465e5ce48622606299cb47833efc3fb235ba15543b81f850722f443"
    },
    "libxfixes3": {
        "filename": "libxfixes3_6.0.0-2+b4_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxfixes/libxfixes3_6.0.0-2+b4_amd64.deb",
        "sha256": "3fdd95d86d8e9d63e11f52070935c8f9f912c36aa3b17338d969f7685f3ed4fb"
    },
    "libxi6": {
        "filename": "libxi6_1.8.2-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxi/libxi6_1.8.2-1_amd64.deb",
        "sha256": "093d0903f35bb7a9f6815180ee040e6951fecf9b66c128cd72f064710210606e"
    },
    "libxkbcommon0": {
        "filename": "libxkbcommon0_1.7.0-2_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxkbcommon/libxkbcommon0_1.7.0-2_amd64.deb",
        "sha256": "f75ee544f55acc6a271debfab3ea4ae0458afc89d81cfe1a71137e07d4895b86"
    },
    "libxrandr2": {
        "filename": "libxrandr2_1.5.4-1+b3_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxrandr/libxrandr2_1.5.4-1+b3_amd64.deb",
        "sha256": "11e3490de93a8bbee3daba719cb8e1325a26fb3c125525c34bdcb7deb05eb9b2"
    },
    "libxrender1": {
        "filename": "libxrender1_0.9.12-1_amd64.deb",
        "url": "https://deb.debian.org/debian/pool/main/libx/libxrender/libxrender1_0.9.12-1_amd64.deb",
        "sha256": "9d042dfd5e613be1e02e6ddd0c5c4adef19c5eb08f6db838c2eba672c496dca4"
    }
}
