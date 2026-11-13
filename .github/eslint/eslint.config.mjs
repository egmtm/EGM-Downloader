// ESLint config of the JavaScript lint workflow (.github/workflows/lint-javascript.yml): the
// recommended rules, with an empty catch block allowed (the shells' best effort calls ignore their
// errors on purpose). The linted files are CommonJS run by Node and Electron.
import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    languageOptions: { sourceType: "commonjs", globals: globals.node },
    rules: { "no-empty": ["error", { allowEmptyCatch: true }] },
  },
];
