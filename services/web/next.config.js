/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  images: {
    domains: ["placeholder.heimdex.local"],
    unoptimized: true,
  },
};

module.exports = nextConfig;
