import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const env = { ...process.env }
if (!String(env.NEXT_PUBLIC_API_URL || '').trim()) {
    env.NEXT_PUBLIC_API_URL = '/'
}

const nextBin = resolve('node_modules/next/dist/bin/next')
const result = spawnSync(process.execPath, [nextBin, 'build'], {
    env,
    stdio: 'inherit',
})

if (result.error) {
    throw result.error
}

process.exit(result.status ?? 1)
