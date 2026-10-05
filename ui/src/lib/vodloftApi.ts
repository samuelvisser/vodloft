export const vodloftBase = () => `${(window as any).appConfig?.API_URL || '/api'}/vodloft`

export function vodloftFormRequest(path: string, method: string, values: unknown) {
    return fetch(`${vodloftBase()}${path}`, {method, credentials: 'include',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(values)})
}

export async function vodloftApi<T>(path: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${vodloftBase()}${path}`, {credentials: 'include', ...options,
        headers: {'Content-Type': 'application/json', ...options?.headers}})
    if (!response.ok) {
        const body = await response.json().catch(() => null)
        const detail = typeof body?.detail === 'string' ? body.detail : body?.error?.message
        throw new Error(detail || `Request failed (HTTP ${response.status})`)
    }
    return response.status === 204 ? undefined as T : response.json() as Promise<T>
}
