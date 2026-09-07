// Semantic CSS linting only; oxfmt owns formatting. Lints the plain .css files
// under src/styles/; the scoped <style> blocks in .astro/.svelte components are
// invisible to stylelint without a customSyntax parser, which isn't worth the
// lift here.
export default {
  extends: ["stylelint-config-standard"],
  rules: {
    "no-descending-specificity": null,
    "comment-empty-line-before": null,
    "custom-property-empty-line-before": null,
    "value-keyword-case": null,
    "import-notation": null,
    "hue-degree-notation": null, // oklch hues are written unitless in tokens.css
    "selector-class-pattern": null, // BEM-style names: ledger__date, item__rubric
    "property-no-vendor-prefix": null, // -webkit-text-size-adjust still needs the prefix
  },
};
