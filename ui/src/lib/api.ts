/** How the UI reaches the VODLoft backend. */

/** The backend address followed by ``path``, such as ``apiUrl('/videos')``. */
export function apiUrl(path = ''): string {
    const base = ((window as any).appConfig?.API_URL || '/api').replace(/\/+$/, '')
    return `${base}${path}`
}

/** A refused request, with the backend's explanation as its message. */
export class ApiError extends Error {
    readonly status: number

    constructor(message: string, status: number) {
        super(message)
        this.name = 'ApiError'
        this.status = status
    }
}

/** The backend's explanation of a refused request, or its HTTP status when it gave none. */
export async function errorDetail(response: Response): Promise<string> {
    try {
        const body = await response.json()
        if (typeof body?.detail === 'string' && body.detail.trim()) return body.detail
        // A refusal about one field, made for a form, read where no form shows it.
        const messages = Array.isArray(body?.detail)
            ? body.detail.map((item: {msg?: unknown}) => item?.msg).filter((msg: unknown) => typeof msg === 'string' && msg.trim())
            : []
        if (messages.length) return messages.join(' ')
    } catch {
        // Keep the status text when the body is not JSON.
    }
    return `HTTP ${response.status}`
}

export async function responseError(response: Response): Promise<ApiError> {
    return new ApiError(await errorDetail(response), response.status)
}

/** A request to the backend with the session cookie, sending ``json`` as the body when given. */
export function apiFetch(path: string, {json, headers, ...init}: RequestInit & {json?: unknown} = {}): Promise<Response> {
    return fetch(apiUrl(path), {
        credentials: 'include',
        ...init,
        headers: json === undefined ? headers : {'Content-Type': 'application/json', ...headers},
        body: json === undefined ? init.body : JSON.stringify(json),
    })
}

/** A request whose answer is read with ``parse``, such as a Zod schema's; a refusal throws an ``ApiError``. */
export async function apiJson<T>(
    path: string, parse: (data: unknown) => T, init?: RequestInit & {json?: unknown},
): Promise<T> {
    const response = await apiFetch(path, init)
    if (!response.ok) throw await responseError(response)
    return parse(await response.json())
}

/** The full address of one of VODLoft's public paths, such as an IPTV playlist, on the address VODLoft is reached on. */
export function publicAddress(path: string): string {
    const base = apiUrl().replace(/\/api$/, '')
    return new URL(`${base}${path}`, window.location.href).href
}
