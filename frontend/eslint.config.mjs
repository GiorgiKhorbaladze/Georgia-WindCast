import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // Security: no raw-HTML sinks anywhere (docs/security/THREAT-MODEL.md, XSS). Build DOM nodes
    // or JSX instead; values from the API are then never interpreted as markup.
    rules: {
      "react/no-danger": "error",
      "no-restricted-properties": [
        "error",
        { property: "innerHTML", message: "Use textContent/DOM nodes or JSX (no HTML sinks)." },
        { property: "outerHTML", message: "Use DOM nodes or JSX (no HTML sinks)." },
        { property: "insertAdjacentHTML", message: "Use DOM nodes or JSX (no HTML sinks)." },
      ],
      "no-restricted-syntax": [
        "error",
        { selector: "CallExpression[callee.property.name='write'][callee.object.name='document']", message: "document.write is not allowed." },
        { selector: "CallExpression[callee.name='eval']", message: "eval is not allowed." },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "public/vendor/**",
  ]),
]);

export default eslintConfig;
