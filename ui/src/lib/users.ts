import {useQuery} from '@tanstack/react-query'
import {
    AccessOptionsReadSchema,
    UserAccountsSettingsReadSchema,
    UserReadSchema,
    type AccessOptionsRead,
    type UserAccountsSettingsRead,
    type UserRead,
} from '../types/schemas/user'
import {apiUrl} from './api'

function base(): string {
    return (apiUrl()).replace(/\/+$/, '')
}

async function readJson<T>(path: string, parse: (data: unknown) => T, signal?: AbortSignal): Promise<T> {
    const response = await fetch(`${base()}${path}`, {credentials: 'include', signal})
    if (!response.ok) throw new Error(await errorMessage(response))
    return parse(await response.json())
}

export async function errorMessage(response: Response): Promise<string> {
    try {
        const payload = await response.json()
        if (typeof payload?.detail === 'string') return payload.detail
        if (Array.isArray(payload?.detail) && typeof payload.detail[0]?.msg === 'string') return payload.detail[0].msg
    } catch {
        // No JSON error body.
    }
    return `Something went wrong (HTTP ${response.status})`
}

export const USERS_KEY = ['users'] as const
export const USER_ACCOUNTS_KEY = ['userAccountsSettings'] as const

export function useUsers(enabled = true) {
    return useQuery<UserRead[]>({
        queryKey: USERS_KEY,
        enabled,
        queryFn: ({signal}) => readJson('/users', (data) => UserReadSchema.array().parse(data), signal),
    })
}

export function useUserAccountsSettings() {
    return useQuery<UserAccountsSettingsRead>({
        queryKey: USER_ACCOUNTS_KEY,
        queryFn: ({signal}) => readJson('/users/settings', (data) => UserAccountsSettingsReadSchema.parse(data), signal),
    })
}

export function useAccessOptions() {
    return useQuery<AccessOptionsRead>({
        queryKey: ['accessOptions'],
        staleTime: Infinity,
        queryFn: ({signal}) => readJson('/users/access-options', (data) => AccessOptionsReadSchema.parse(data), signal),
    })
}

/** Send a request to the users API; the caller decides what a failure means. */
export function usersRequest(path: string, method: string, body?: unknown): Promise<Response> {
    return fetch(`${base()}/users${path}`, {
        method,
        credentials: 'include',
        headers: body === undefined ? undefined : {'Content-Type': 'application/json'},
        body: body === undefined ? undefined : JSON.stringify(body),
    })
}
