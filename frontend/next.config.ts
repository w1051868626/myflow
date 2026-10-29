import type { NextConfig } from "next";

const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
const config: NextConfig = {
  output: "standalone",
  // JSON uploads carry up to 20 MB of media encoded as Base64.
  experimental: { proxyClientMaxBodySize: "32mb" },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/artifacts/:path*", destination: `${backend}/artifacts/:path*` },
    ];
  },
};
export default config;
