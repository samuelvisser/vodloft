/**
 * What the extension's popup and background share: the browser's extension API, the address of the user's VODLoft,
 * and telling a VODLoft that is down from one that refused.
 */
import {ApiError} from '../lib/api'

/* eslint-disable @typescript-eslint/no-explicit-any */
/** Firefox's ``browser`` or Chrome's ``chrome``: both take promises in Manifest V3. */
export const ext: any = (globalThis as any).browser ?? (globalThis as any).chrome
/** Firefox alone can tell its own version; Chrome has a ``browser`` namespace too nowadays. */
export const isFirefox = typeof ext?.runtime?.getBrowserInfo === 'function'

const ADDRESS_KEY = 'vodloft'

/** The address VODLoft is reached on, without a trailing slash, or null before the user gave one. */
export async function storedAddress(): Promise<string | null> {
    const {[ADDRESS_KEY]: address} = await ext.storage.local.get(ADDRESS_KEY)
    return typeof address === 'string' && address ? address : null
}

export async function storeAddress(address: string): Promise<void> {
    await ext.storage.local.set({[ADDRESS_KEY]: address})
}

/** The address the user typed, as the origin and path VODLoft is reached on. */
export function normalAddress(typed: string): string {
    let text = typed.trim()
    if (!/^https?:\/\//i.test(text)) text = `https://${text}`
    const url = new URL(text)
    return `${url.origin}${url.pathname.replace(/\/+$/, '')}`
}

/** Access to the VODLoft address: the extension talks to its API from its own pages, which need it. */
export function vodloftOrigins(address: string) {
    return {origins: [`${new URL(address).origin}/*`]}
}

/** Point VODLoft's own API code at the user's VODLoft, as its UI's config does. */
export function connectTo(address: string): void {
    (globalThis as any).appConfig = {API_URL: `${address}/api`}
}

/** VODLoft did not answer: it is down, restarting, or the network is. */
export function unreachable(exc: unknown): boolean {
    if (exc instanceof ApiError) return exc.status === 502 || exc.status === 503 || exc.status === 504
    // fetch rejects with a TypeError when nothing answers.
    return exc instanceof TypeError
}

export function signedOut(exc: unknown): boolean {
    return exc instanceof ApiError && exc.status === 401
}

export function messageOf(exc: unknown): string {
    return exc instanceof Error ? exc.message : String(exc)
}

export const isWebPage = (url: unknown): url is string => typeof url === 'string' && /^https?:\/\//i.test(url)
