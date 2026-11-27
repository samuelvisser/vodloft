// Sends the cookies this browser has for the site of the current tab to the user's own VODLoft, which keeps them as
// that site's cookies file. VODLoft tells which site the page is on and which domains its cookies are for; the
// extension reads only those cookies, and only when the user chooses Send.

const api = globalThis.browser ?? globalThis.chrome
// Firefox alone can tell its own version; Chrome has a `browser` namespace too nowadays.
const isFirefox = typeof api.runtime.getBrowserInfo === 'function'
const ALL_SITES = {origins: ['<all_urls>']}

const $ = (id) => document.getElementById(id)

const show = (id) => {
    for (const section of ['setup', 'send', 'no-page']) $(section).hidden = section !== id
}

/** The address VODLoft is reached on, without a trailing slash, or null before the user gave one. */
async function vodloftAddress() {
    const {vodloft} = await api.storage.local.get('vodloft')
    return typeof vodloft === 'string' && vodloft ? vodloft : null
}

/** The address the user typed, as the origin and path VODLoft is reached on. */
function normalAddress(typed) {
    let text = typed.trim()
    if (!/^https?:\/\//i.test(text)) text = `https://${text}`
    const url = new URL(text)
    const path = url.pathname.replace(/\/+$/, '')
    return `${url.origin}${path}`
}

async function currentTab() {
    const [tab] = await api.tabs.query({active: true, currentWindow: true})
    return tab
}

const isWebPage = (url) => typeof url === 'string' && /^https?:\/\//i.test(url)

/** The cookie store of the tab: a private window's, or a Firefox container's, has cookies of its own. */
async function cookieStoreOf(tab) {
    if (tab.cookieStoreId) return tab.cookieStoreId
    const stores = await api.cookies.getAllCookieStores()
    return stores.find((store) => store.tabIds.includes(tab.id))?.id
}

/** Every cookie of the store for the domains (and their subdomains), and the ones the page itself gets. */
async function cookiesFor(tab, domains) {
    const storeId = await cookieStoreOf(tab)
    // Firefox refuses to list cookies without this while first-party isolation is on.
    const extra = isFirefox ? {firstPartyDomain: null} : {}
    const asks = [
        ...domains.map((domain) => api.cookies.getAll({domain, storeId, ...extra})),
        api.cookies.getAll({url: tab.url, storeId, ...extra}),
    ]
    const found = new Map()
    for (const cookies of await Promise.all(asks)) {
        for (const cookie of cookies) found.set(`${cookie.domain}\t${cookie.path}\t${cookie.name}`, cookie)
    }
    return [...found.values()]
}

/** The cookies as a Netscape cookies.txt file, the way yt-dlp reads them. */
function cookiesFile(cookies) {
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

/** What VODLoft said when it refused, or a sentence for its HTTP status. */
async function refusal(response) {
    if (response.status === 401) return 'Sign in to VODLoft in this browser first, then try again.'
    try {
        const body = await response.json()
        if (typeof body?.detail === 'string') return body.detail
        if (Array.isArray(body?.detail)) {
            const messages = body.detail.map((item) => item?.msg).filter(Boolean)
            if (messages.length) return messages.join(' ')
        }
    } catch {
        // Not VODLoft's JSON: fall back to the status.
    }
    return `VODLoft answered with HTTP ${response.status}. Is the address right?`
}

async function vodloft(base, path, init = {}) {
    try {
        return await fetch(`${base}/api${path}`, {credentials: 'include', ...init})
    } catch {
        throw new Error(`Could not reach VODLoft at ${base}. Check the address, and that VODLoft is running.`)
    }
}

function report(text, tone, base) {
    const result = $('result')
    result.textContent = text
    result.className = tone
    result.hidden = false
    const open = $('open-vodloft')
    open.href = tone === 'ok' ? `${base}/settings?tab=sources` : base
    open.textContent = tone === 'ok' ? 'Open Authentication' : 'Open VODLoft'
    $('result-actions').hidden = false
}

async function send(base, tab) {
    const button = $('send-button')
    button.disabled = true
    button.textContent = 'Sending…'
    $('result').hidden = true
    $('result-actions').hidden = true
    try {
        if (!await api.permissions.contains(ALL_SITES)) {
            report('The extension may not read cookies yet. Choose Change, then Save, and allow it.', 'problem', base)
            return
        }
        const found = await vodloft(base, `/sources/authentication/site-of-page?url=${encodeURIComponent(tab.url)}`)
        if (!found.ok) return report(await refusal(found), 'problem', base)
        const site = await found.json()
        if (!site.takesCookies) {
            return report(`${site.name} has a sign-in of its own in VODLoft, and takes no cookies.`, 'problem', base)
        }
        const cookies = await cookiesFor(tab, site.domains)
        if (!cookies.length) {
            return report(`This browser has no cookies for ${site.name}. Sign in on ${site.name} first.`, 'problem', base)
        }
        const saved = await vodloft(base, '/sources/authentication/browser-cookies', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: tab.url, content: cookiesFile(cookies)}),
        })
        if (!saved.ok) return report(await refusal(saved), 'problem', base)
        const listing = await saved.json()
        const count = listing.cookieCount === 1 ? '1 cookie' : `${listing.cookieCount} cookies`
        report(`VODLoft has ${count} for ${listing.name} now, and signs in with them there.`, 'ok', base)
    } catch (error) {
        report(error instanceof Error ? error.message : String(error), 'problem', base)
    } finally {
        button.disabled = false
        button.textContent = 'Send cookies to VODLoft'
    }
}

async function showSetup(tab, current) {
    show('setup')
    const input = $('address')
    // The tab may show VODLoft itself, which is the address to keep.
    input.value = current ?? (isWebPage(tab?.url) && /vodloft/i.test(tab.title ?? '') ? new URL(tab.url).origin : '')
    $('setup-cancel').hidden = !current
    input.focus()
}

async function start() {
    const tab = await currentTab()
    const base = await vodloftAddress()
    if (!base) return showSetup(tab, null)
    if (!isWebPage(tab?.url)) {
        $('vodloft-address-no-page').textContent = base
        return show('no-page')
    }
    $('page-host').textContent = new URL(tab.url).hostname.replace(/^www\./, '')
    $('vodloft-address').textContent = base
    show('send')
}

$('setup').addEventListener('submit', async (event) => {
    event.preventDefault()
    const problem = $('setup-error')
    problem.hidden = true
    let address
    try {
        address = normalAddress($('address').value)
    } catch {
        problem.textContent = 'Type the address you open VODLoft on, such as https://vodloft.example.com'
        problem.hidden = false
        return
    }
    // Asked before anything else is awaited: browsers only ask for permissions right on a click. Firefox may close
    // this popup to ask, so the address is saved meanwhile.
    const asking = api.permissions.request(ALL_SITES)
    await api.storage.local.set({vodloft: address})
    const allowed = await asking.catch(() => false)
    if (!allowed) {
        problem.textContent = 'The extension can only send cookies once you allow it to read them.'
        problem.hidden = false
        return
    }
    await start()
})

$('send-button').addEventListener('click', async () => {
    const base = await vodloftAddress()
    const tab = await currentTab()
    if (base && tab) await send(base, tab)
})

for (const id of ['change', 'change-no-page']) {
    $(id).addEventListener('click', async () => showSetup(await currentTab(), await vodloftAddress()))
}

$('setup-cancel').addEventListener('click', () => void start())

void start()
