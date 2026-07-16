import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { NextConfig } from 'next'
import { parseChangelog } from './src/lib/release'

const projectRoot = join(dirname(fileURLToPath(import.meta.url)), '..')

function assertProductionApiUrl() {
    const apiUrl = String(process.env.NEXT_PUBLIC_API_URL || '').trim()
    const loopbackUrl = /^(?:https?:)?\/\/(?:localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|\[::1\])(?::|\/|$)/i
    if (process.env.NODE_ENV === 'production' && loopbackUrl.test(apiUrl)) {
        throw new Error(
            `Refusing to build a production frontend with loopback NEXT_PUBLIC_API_URL=${apiUrl}. ` +
            'Use NEXT_PUBLIC_API_URL=/ for same-origin deployment.',
        )
    }
}

assertProductionApiUrl()

function readAppVersion() {
    try {
        const version = readFileSync(join(projectRoot, 'VERSION'), 'utf-8').trim()
        return version || '0.0.0'
    } catch {
        return '0.0.0'
    }
}

const appVersion = process.env.NEXT_PUBLIC_APP_VERSION || readAppVersion()
let appReleases = '[]'
try {
    appReleases = JSON.stringify(parseChangelog(readFileSync(join(projectRoot, 'CHANGELOG.md'), 'utf-8')))
} catch {}

const nextConfig: NextConfig = {
    allowedDevOrigins: ['127.0.0.1'],
    env: {
        NEXT_PUBLIC_APP_VERSION: appVersion,
        NEXT_PUBLIC_APP_RELEASES: appReleases,
        NEXT_PUBLIC_REPOSITORY_URL: process.env.NEXT_PUBLIC_REPOSITORY_URL || 'https://github.com/owen891/chatgpt2api',
        NEXT_PUBLIC_REPOSITORY_BRANCH: process.env.NEXT_PUBLIC_REPOSITORY_BRANCH || 'main',
    },
    output: 'export',
    trailingSlash: true,
    images: {
        unoptimized: true,
    },
    typescript: {
        ignoreBuildErrors: true,
    },
}

export default nextConfig
