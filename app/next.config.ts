import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // native sqlite driver must stay a Node external, not be bundled
  serverExternalPackages: ["better-sqlite3"],
  // a stray package-lock.json exists at E:\ — pin the workspace root
  turbopack: { root: __dirname },
};

export default nextConfig;
