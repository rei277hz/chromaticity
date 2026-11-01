/* Match Chinese phrases directly; mdBook's English stemmer drops CJK text. */
(function (root) {
    "use strict";
    const normalize = text => String(text || "").normalize("NFKC").toLocaleLowerCase("zh-Hans");
    function create(documents) {
        const entries = Object.entries(documents).map(([ref, doc]) => ({
            ref, doc, title: normalize(doc.title),
            body: normalize(doc.body), breadcrumbs: normalize(doc.breadcrumbs),
        }));
        return {search(query, options = {}) {
            const terms = normalize(query).trim().split(/\s+/).filter(Boolean);
            if (!terms.length) return [];
            const results = [];
            for (const entry of entries) {
                const scores = terms.map(term => (entry.title.includes(term) ? 4 : 0) +
                    (entry.body.includes(term) ? 1 : 0) + (entry.breadcrumbs.includes(term) ? 1 : 0));
                const matched = options.bool === "OR" ? scores.some(Boolean) : scores.every(Boolean);
                if (matched) results.push({ref: entry.ref, doc: entry.doc, score: scores.reduce((a,b) => a+b, 0)});
            }
            return results.sort((a,b) => b.score-a.score || Number(a.ref)-Number(b.ref));
        }};
    }
    root.PGChineseSearch = {create};
})(typeof window === "undefined" ? globalThis : window);
