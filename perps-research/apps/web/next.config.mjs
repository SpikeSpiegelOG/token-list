/** @type {import('next').NextConfig} */
const nextConfig = {
  // DuckDB ships per-platform native bindings via optional deps. Mark the
  // umbrella packages AND every platform variant as external so webpack
  // doesn't try to resolve the .node files for OSes we're not running on.
  serverExternalPackages: [
    '@duckdb/node-api',
    '@duckdb/node-bindings',
    '@duckdb/node-bindings-darwin-arm64',
    '@duckdb/node-bindings-darwin-x64',
    '@duckdb/node-bindings-linux-arm64',
    '@duckdb/node-bindings-linux-x64',
    '@duckdb/node-bindings-win32-x64',
    'ws',
    'bufferutil',
    'utf-8-validate',
  ],
  transpilePackages: [
    '@perps/backtest',
    '@perps/core',
    '@perps/indicators',
    '@perps/macro',
    '@perps/paper',
    '@perps/storage',
    '@perps/strategies',
    '@perps/venue-binance',
    '@perps/venue-hyperliquid',
  ],
  reactStrictMode: true,
  webpack: (config, { isServer }) => {
    if (isServer) {
      // Belt-and-braces: the platform-specific .node files only exist for
      // the current host, so ignore the dynamic `require('@duckdb/node-
      // bindings-<plat>-<arch>/duckdb.node')` calls that target others.
      config.externals = [
        ...(config.externals ?? []),
        ({ request }, callback) => {
          if (
            typeof request === 'string' &&
            request.startsWith('@duckdb/node-bindings-')
          ) {
            return callback(null, `commonjs ${request}`);
          }
          callback();
        },
      ];
    }
    return config;
  },
};

export default nextConfig;
