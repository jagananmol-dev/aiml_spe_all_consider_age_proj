/** @type {import('jest').Config} */
const config = {
  testEnvironment: "node",
  preset: "ts-jest",
  roots: ["<rootDir>/src"],
  testMatch: ["**/__tests__/**/*.test.ts"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  transform: {
    "^.+\\.tsx?$": [
      "ts-jest",
      {
        tsconfig: {
          // Relax for test files — avoids strict mode issues in mocks
          strict: false,
          esModuleInterop: true,
        },
      },
    ],
  },
  // No global setup file needed — mocks are defined per-test file
  coverageDirectory: "coverage",
  coverageReporters: ["text", "lcov", "clover"],
  collectCoverageFrom: [
    "src/app/api/**/*.ts",
    "src/lib/**/*.ts",
    "src/middleware.ts",
    "!src/**/*.d.ts",
  ],
  coverageThreshold: {
    global: {
      statements: 80,
      branches: 75,
      functions: 80,
      lines: 80,
    },
  },
  // Ignore Next.js-specific internals
  modulePathIgnorePatterns: ["<rootDir>/.next", "<rootDir>/node_modules"],
};

module.exports = config;
