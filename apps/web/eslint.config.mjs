import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    // Jest tests load modules with require() after jest.mock(), and mock
    // loosely typed collaborators
    files: ["src/__tests__/**"],
    rules: {
      "@typescript-eslint/no-require-imports": "off",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unsafe-function-type": "off",
    },
  },
  { ignores: [".next/**", "node_modules/**", "coverage/**", "next-env.d.ts", "jest.config.js"] },
];

export default eslintConfig;
