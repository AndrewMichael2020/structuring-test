/** @type {import('jest').Config} */
const config = {
  projects: [
    // Frontend tests (React)
    {
      displayName: 'client',
      testEnvironment: 'jest-environment-jsdom',
      testMatch: ['<rootDir>/src/**/*.test.jsx'],
      setupFilesAfterEnv: ['<rootDir>/src/test/setupTests.js'],
      moduleNameMapper: {
        '\\.(css|less)$': 'identity-obj-proxy',
      },
    },
    // Backend tests (Express)
    {
      displayName: 'server',
      testEnvironment: 'node',
      testMatch: ['<rootDir>/server/**/*.test.js'],
      transform: {}, // Disable Babel transformation for server tests
    },
  ],
};

module.exports = config;