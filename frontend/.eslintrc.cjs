/* eslint-env node */
require("@rushstack/eslint-patch/modern-module-resolution");

module.exports = {
  root: true,
  env: {
    browser: true,
  },
  ignorePatterns: ["dist/**"],
  extends: [
    "plugin:vue/recommended",
    "eslint:recommended",
    "@vue/eslint-config-typescript",
  ],
  parser: "vue-eslint-parser",
  parserOptions: {
    ecmaVersion: "latest",
  },
  rules: {
    "vue/multi-word-component-names": "off",
    "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
  },
  overrides: [
    {
      files: ["**/ChatPortalView.vue"],
      rules: {
        "vue/no-v-html": "off",
      },
    },
  ],
};
