import type {ReactNode} from 'react'
import {apiUrl} from '../../lib/api'

/** The address the browser extension reaches this VODLoft on: where its API is, without ``/api``. */
function vodloftAddress() {
    return new URL(apiUrl(), window.location.href).href.replace(/\/api\/?$/, '')
}

/**
 * How to install VODLoft's browser extension, as steps to fold open, followed by ``children``: the steps of what the
 * place that offers it uses it for, such as adding the page's media, or sending a site's cookies.
 */
export default function BrowserExtensionSteps({summary, className = '', children}: {
    summary: string; className?: string; children: ReactNode
}) {
    return (
        <details className={`youtube-api-guide ${className}`.trim()}>
            <summary>{summary}</summary>
            <ol>
                <li>
                    <span>Download VODLoft&apos;s browser extension and unzip it.</span>
                    <a className="btn" href={apiUrl('/browser-extension')} download>Download</a>
                </li>
                <li>
                    <span>
                        In Chrome, Edge or Brave, open <code>chrome://extensions</code>, turn on Developer mode, choose
                        Load unpacked and pick the unzipped folder. In Firefox, open{' '}
                        <code>about:debugging#/runtime/this-firefox</code>, choose Load Temporary Add-on and pick the
                        folder&apos;s <code>manifest.json</code>.
                    </span>
                </li>
                <li>
                    <span>
                        Click the VODLoft icon in your browser&apos;s toolbar, fill in <code>{vodloftAddress()}</code>,
                        choose Save and allow it to reach VODLoft. Stay signed in to VODLoft in the same browser.
                    </span>
                </li>
                {children}
            </ol>
        </details>
    )
}
