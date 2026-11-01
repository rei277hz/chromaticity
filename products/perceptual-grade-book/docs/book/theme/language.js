/* Language preference is scoped to this deployed book, including project paths. */
(function (root) {
    "use strict";
    const supported = ["en", "zh-Hans"];
    function chooseLanguage(saved, locales) {
        if (supported.includes(saved)) return saved;
        for (const raw of locales || []) {
            const locale = String(raw).replaceAll("_", "-").toLowerCase();
            if (/^en(?:-|$)/.test(locale)) return "en";
            if (/^zh(?:-|$)/.test(locale)) {
                const script = locale.match(/-([a-z]{4})(?:-|$)/)?.[1];
                if (script) { if (script === "hans") return "zh-Hans"; else continue; }
                if (/(?:^|-)(?:tw|hk|mo)(?:-|$)/.test(locale)) continue;
                if (locale === "zh" || /(?:^|-)(?:cn|sg|my)(?:-|$)/.test(locale)) return "zh-Hans";
            }
        }
        return "en";
    }
    root.PGLanguage = {chooseLanguage};
    if (!root.document) return;
    const script = document.currentScript;
    const base = new URL(".", script.src);
    const key = "perceptual-grade-language:" + base.pathname;
    function read() { try { return localStorage.getItem(key); } catch { return null; } }
    function save(value) { try { localStorage.setItem(key, value); } catch {} }
    if (document.documentElement.dataset.languageEntry === "true") {
        const selected = chooseLanguage(read(), navigator.languages || [navigator.language]);
        const target = new URL(selected + "/index.html", base);
        target.search = location.search;
        target.hash = location.hash;
        location.replace(target.href);
    }
    document.addEventListener("DOMContentLoaded", () => {
        for (const link of document.querySelectorAll("a[data-book-language]")) {
            link.addEventListener("click", () => save(link.dataset.bookLanguage));
        }
        const picker = document.querySelector(".language-picker");
        if (!picker) return;
        const trigger = picker.querySelector("summary");
        picker.addEventListener("toggle", () => trigger.setAttribute("aria-expanded", String(picker.open)));
        document.addEventListener("click", event => { if (!picker.contains(event.target)) picker.open = false; });
        document.addEventListener("keydown", event => {
            if (event.key === "Escape" && picker.open) { picker.open = false; trigger.focus(); }
        });
    });
})(typeof window === "undefined" ? globalThis : window);
