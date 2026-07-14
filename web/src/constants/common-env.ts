const repositoryUrl = process.env.NEXT_PUBLIC_REPOSITORY_URL || 'https://github.com/owen891/chatgpt2api'
const repositoryBranch = process.env.NEXT_PUBLIC_REPOSITORY_BRANCH || 'main'
const sourceRepositoryUrl = 'https://github.com/basketikun/chatgpt2api'

function toRawGithubBase(url: string, branch: string) {
    const normalized = url.replace(/\.git$/, '').replace(/\/$/, '')
    const githubMatch = normalized.match(/^https:\/\/github\.com\/([^/]+)\/([^/]+)$/)
    if (!githubMatch) return ''
    return `https://raw.githubusercontent.com/${githubMatch[1]}/${githubMatch[2]}/${branch}`
}

const repositoryRawBaseUrl = toRawGithubBase(repositoryUrl, repositoryBranch)

const webConfig = {
    apiUrl: process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === 'development' ? 'http://127.0.0.1:8000' : ''),
    appVersion: process.env.NEXT_PUBLIC_APP_VERSION || '0.0.0',
    repositoryUrl,
    repositoryBranch,
    repositoryRawBaseUrl,
    sourceRepositoryUrl,
}

export default webConfig
