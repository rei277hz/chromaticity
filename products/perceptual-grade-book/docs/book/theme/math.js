/* The Buck2-generated head loads pinned KaTeX from the CDN before this event. */
document.addEventListener("DOMContentLoaded", () => {
    for (const equation of document.querySelectorAll("[data-tex]")) {
        try {
            katex.render(equation.dataset.tex, equation, {
                displayMode: equation.classList.contains("grade-equation"),
                throwOnError: true,
                trust: false,
                strict: "warn"
            });
        } catch (error) {
            equation.textContent = equation.dataset.tex;
            equation.classList.add("math-error");
            console.error("Equation rendering failed", error);
        }
    }
});
