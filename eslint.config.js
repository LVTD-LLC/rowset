const js = require("@eslint/js");

module.exports = [
  js.configs.recommended,
  {
    files: ["frontend/src/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        AbortController: "readonly",
        clearTimeout: "readonly",
        confirm: "readonly",
        console: "readonly",
        CustomEvent: "readonly",
        document: "readonly",
        fetch: "readonly",
        FormData: "readonly",
        localStorage: "readonly",
        navigator: "readonly",
        setTimeout: "readonly",
        URLSearchParams: "readonly",
        window: "readonly",
      },
    },
    rules: {
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", caughtErrors: "none" }],
      semi: "error",
    },
  },
];
