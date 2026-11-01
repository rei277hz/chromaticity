/* Local reader controls: print images and automatic theme. */
document.addEventListener("DOMContentLoaded", () => {
    // Animated WebPs loop intrinsically. Still companions are only for print.
    for (const image of document.querySelectorAll("figure.grade-demo img[data-still]")) {
        const animation = image.getAttribute("src");
        window.addEventListener("beforeprint", () => { image.src = image.dataset.still; });
        window.addEventListener("afterprint", () => { image.src = animation; });
    }
    const dark = window.matchMedia("(prefers-color-scheme: dark)");
    const read = key => { try { return localStorage.getItem(key); } catch { return null; } };
    const write = (key,value) => { try { localStorage.setItem(key,value); } catch {} };
    let automatic = read("grade-theme-auto") === "true" ||
        (read("grade-theme-auto") === null && read("mdbook-theme") === null);
    const autoButton = document.getElementById("grade-theme-auto");
    const applyAuto = () => {
        if (!automatic) return;
        const theme = dark.matches ? "navy" : "light";
        document.documentElement.classList.remove("light","rust","coal","navy","ayu");
        document.documentElement.classList.add(theme);
        write("mdbook-theme",theme);
        write("grade-theme-auto","true");
    };
    autoButton?.addEventListener("click", () => {
        automatic = true;
        applyAuto();
        document.getElementById("mdbook-theme-toggle")?.click();
    });
    for (const button of document.querySelectorAll("#mdbook-theme-light,#mdbook-theme-navy")) {
        button.addEventListener("click", () => {
            automatic = false;
            write("grade-theme-auto","false");
        }, true);
    }
    dark.addEventListener("change",applyAuto);
    applyAuto();
});
