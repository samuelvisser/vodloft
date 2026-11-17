import {InputHTMLAttributes, ReactNode, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'

type Props = {
    id: string
    label: string
    /** What the address is, for the buttons, such as "RSS feed URL". */
    what: string
    /** The address, for copying it. */
    value: string | undefined
    /** The input's own props, for an address that can be edited; otherwise it is read-only. */
    inputProps?: InputHTMLAttributes<HTMLInputElement>
    onRegenerate?: () => void | Promise<void>
    regenerating?: boolean
    error?: string
    help: ReactNode
}

/** A secret address an app subscribes to, with Copy and, where it can be replaced, Regenerate. */
export default function StreamAddressField({
    id,
    label,
    what,
    value,
    inputProps,
    onRegenerate,
    regenerating,
    error,
    help,
}: Props) {
    const [copied, setCopied] = useState(false)

    const onCopy = async () => {
        if (!value) return
        try {
            await navigator.clipboard.writeText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
        } catch {
            // The field remains selectable when clipboard access is unavailable.
        }
    }

    return (
        <div className="form-row">
            <label htmlFor={id}>{label}</label>
            <div className={`rss-feed-url-group${error ? ' rss-feed-url-group-invalid' : ''}`}>
                <input
                    id={id}
                    className="input rss-feed-url-input"
                    type="text"
                    {...(inputProps ?? {value: value ?? '', readOnly: true})}
                    aria-invalid={!!error}
                    aria-describedby={error ? `${id}-error` : `${id}-help`}
                />
                <div className="rss-feed-url-actions">
                    <button
                        type="button"
                        className="rss-feed-url-action"
                        onClick={onCopy}
                        disabled={!value}
                        aria-label={copied ? `${what} copied` : `Copy ${what}`}
                        title={copied ? 'Copied!' : `Copy ${what}`}
                        aria-live="polite"
                    >
                        <FontAwesomeIcon
                            className="rss-feed-url-action-icon"
                            icon={faIcon('fass', copied ? 'check' : 'copy') as any}
                            aria-hidden="true"
                        />
                        <span className="rss-feed-url-action-text">{copied ? 'Copied!' : 'Copy'}</span>
                    </button>
                    {onRegenerate && (
                        <button
                            type="button"
                            className="rss-feed-url-action rss-feed-url-action-danger"
                            onClick={onRegenerate}
                            disabled={!!regenerating}
                            aria-label={regenerating ? `Regenerating ${what}` : `Regenerate ${what}`}
                            title={regenerating ? 'Regenerating…' : `Regenerate ${what}`}
                        >
                            <FontAwesomeIcon
                                className="rss-feed-url-action-icon"
                                icon={faIcon('fass', regenerating ? 'spinner' : 'arrows-rotate') as any}
                                spin={!!regenerating}
                                aria-hidden="true"
                            />
                            <span className="rss-feed-url-action-text">
                                {regenerating ? 'Regenerating…' : 'Regenerate'}
                            </span>
                        </button>
                    )}
                </div>
            </div>
            {error && (
                <div id={`${id}-error`} className="error" role="alert" aria-live="polite">{error}</div>
            )}
            <div className="help" id={`${id}-help`}>{help}</div>
        </div>
    )
}
