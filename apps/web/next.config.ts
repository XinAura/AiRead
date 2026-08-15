import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@airead/api-client"],
  allowedDevOrigins: process.env.AIREAD_DEV_ORIGIN
    ? [process.env.AIREAD_DEV_ORIGIN]
    : [],
};

export default nextConfig;
