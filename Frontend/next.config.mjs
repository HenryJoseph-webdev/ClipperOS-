/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ['localhost', '127.0.0.1'],
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  async rewrites() {
    const backend = process.env.CLIPPER_API_ORIGIN || 'http://127.0.0.1:5000'
    return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }]
  },
}

export default nextConfig
