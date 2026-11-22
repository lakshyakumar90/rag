/** @type {import('next').NextConfig} */
const nextConfig = {
  // Native Windows runs can avoid packaging symlinks required by standalone output.
  output: process.env.RAG_NATIVE_WEB === "true" ? undefined : "standalone",
};

export default nextConfig;
