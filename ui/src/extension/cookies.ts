/**
 * Sends the cookies this browser has for the site of a tab to VODLoft, which keeps them as that site's cookies file.
 * VODLoft tells which site the page is on and which domains its cookies are for; only those cookies are read, and
 * only when the user chooses Send.
 */
import {z} from 'zod'
import {apiJson} from '../lib/api'
import {ext, isFirefox} from './browser'

/** Reading cookies takes access to every site, asked for only when the user first sends them. */
export const ALL_SITES = {origins: ['<all_urls>']}

const LinkedSiteSchema = z.object({key: z.string(), name: z.string(), domains: z.array(z.string()), takesCookies: z.boolean()})
const SavedCookiesSchema = z.looseObject({name: z.string(), cookieCount: z.number()})

type Tab = {id: number; url: string; cookieStoreId?: string}
type Cookie = {
    domain: string; hostOnly: boolean; path: string; secure: boolean; httpOnly: boolean
    session: boolean; expirationDate?: number; name: string; value: string
}

/** The cookie store of the tab: a private window's, or a Firefox container's, has cookies of its own. */
async function cookieStoreOf(tab: Tab): Promise<string | undefined> {
    if (tab.cookieStoreId) return tab.cookieStoreId
    const stores: {id: string; tabIds: number[]}[] = await ext.cookies.getAllCookieStores()
    return stores.find((store) => store.tabIds.includes(tab.id))?.id
}

/** Every cookie of the store for the domains (and their subdomains), and the ones the page itself gets. */
async function cookiesFor(tab: Tab, domains: string[]): Promise<Cookie[]> {
    const storeId = await cookieStoreOf(tab)
    // Firefox refuses to list cookies without this while first-party isolation is on.
    const extra = isFirefox ? {firstPartyDomain: null} : {}
    const asks: Promise<Cookie[]>[] = [
        ...domains.map((domain) => ext.cookies.getAll({domain, storeId, ...extra})),
        ext.cookies.getAll({url: tab.url, storeId, ...extra}),
    ]
    const found = new Map<string, Cookie>()
    for (const cookies of await Promise.all(asks)) {
        for (const cookie of cookies) found.set(`${cookie.domain}\t${cookie.path}\t${cookie.name}`, cookie)
    }
    return [...found.values()]
}

/** The cookies as a Netscape cookies.txt file, the way yt-dlp reads them. */
function cookiesFile(cookies: Cookie[]): string {
    const lines = cookies.map((cookie) => {
        const domain = cookie.hostOnly || cookie.domain.startsWith('.') ? cookie.domain : `.${cookie.domain}`
        const expires = cookie.session || !cookie.expirationDate ? 0 : Math.floor(cookie.expirationDate)
        return [
            `${cookie.httpOnly ? '#HttpOnly_' : ''}${domain}`,
            cookie.hostOnly ? 'FALSE' : 'TRUE',
            cookie.path,
            cookie.secure ? 'TRUE' : 'FALSE',
            String(expires),
            cookie.name,
            cookie.value,
        ].join('\t')
    })
    return `# Netscape HTTP Cookie File\n# Sent by VODLoft's browser extension.\n\n${lines.join('\n')}\n`
}

/** Send the cookies of the tab's site, and say how it went. Throws what VODLoft refused. */
export async function sendCookies(tab: Tab): Promise<{tone: 'ok' | 'problem'; text: string}> {
    if (!await ext.permissions.contains(ALL_SITES)) {
        return {tone: 'problem', text: 'The extension may not read cookies yet. Choose Send cookies again and allow it.'}
    }
    const site = await apiJson(`/sources/authentication/site-of-page?url=${encodeURIComponent(tab.url)}`, LinkedSiteSchema.parse)
    if (!site.takesCookies) return {tone: 'problem', text: `${site.name} has a sign-in of its own in VODLoft, and takes no cookies.`}
    const cookies = await cookiesFor(tab, site.domains)
    if (!cookies.length) return {tone: 'problem', text: `This browser has no cookies for ${site.name}. Sign in on ${site.name} first.`}
    const saved = await apiJson('/sources/authentication/browser-cookies', SavedCookiesSchema.parse, {
        method: 'POST', json: {url: tab.url, content: cookiesFile(cookies)},
    })
    const count = saved.cookieCount === 1 ? '1 cookie' : `${saved.cookieCount} cookies`
    return {tone: 'ok', text: `VODLoft has ${count} for ${saved.name} now, and signs in with them there.`}
}
