const katex = require(process.argv[2]);

if (katex.version !== "0.19.0") {
  throw new Error(`Expected KaTeX 0.19.0, received ${katex.version}`);
}

let source = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => { source += chunk; });
process.stdin.on("end", () => {
  const expressions = JSON.parse(source);
  const rendered = expressions.map(({tex, display}) => katex.renderToString(tex, {
    displayMode: display,
    output: "htmlAndMathml",
    throwOnError: true,
    strict: "error",
    trust: false,
    macros: {"\\arcsinh": "\\operatorname{arcsinh}"},
  }));
  process.stdout.write(JSON.stringify(rendered));
});
