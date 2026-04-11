/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Enable experimental features for dynamic routing
  experimental: {
    serverComponentsExternalPackages: ['fs', 'path'],
  },
}

module.exports = nextConfig
