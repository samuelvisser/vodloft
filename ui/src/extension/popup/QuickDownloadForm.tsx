import {useEffect, useMemo, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import QuickOptionList from '../../components/QuickDownload/QuickOptionList'
import QuickFormatPanel from '../../components/QuickDownload/QuickFormatPanel'
import {
    choiceFromSettings, choiceSize, choiceSummary, fitChoice, fitRules, ruleProblem, rulesFromSettings, sizeLabel,
    type QuickDownloadSettingsForUser,
} from '../../lib/quickDownloads'
import {
    MP3_BITRATES, QUICK_CODECS, QUICK_QUALITIES,
    type QuickChoice, type QuickDownloadOptions,
} from '../../types/schemas/quick_download'
import {messageOf} from '../browser'
import {sendQueueMessage} from '../queue'

/**
 * What VODLoft can make of any link, for a download chosen while VODLoft cannot be asked: every quality, format and
 * codec, without sizes. VODLoft fits the choice to what the link has once it gets it, as it does for every choice.
 */
export function choicesWithoutVodloft(): QuickDownloadOptions {
    return {
        link: undefined as never,
        refused: null,
        formatChoices: true,
        qualityChoices: true,
        containers: ['mp4', 'mkv'],
        videos: [null, ...QUICK_QUALITIES].map((quality) => ({
            quality, sizeBytes: null, codec: null, codecs: QUICK_CODECS.map((codec) => ({codec, sizeBytes: null})),
        })),
        audio: [{audioFormat: 'm4a', bitrate: null, sizeBytes: null}, ...MP3_BITRATES.map((bitrate) => ({audioFormat: 'mp3' as const, bitrate, sizeBytes: null}))],
        duration: null,
    }
}

type QuickDownloadFormProps = {
    url: string
    sourceKey: string | null
    title: string
    imageUrl: string | null
    /** What the link can be downloaded as; null while VODLoft lists it. */
    options: QuickDownloadOptions | null
    /** The user's Quick download settings, also the last ones VODLoft sent while it cannot be asked now. */
    settings: QuickDownloadSettingsForUser | undefined
    /** VODLoft cannot be asked: the download waits in the extension until it can. */
    waiting: 'vodloft' | 'sign-in' | null
    onQueued: () => void
}

/** Quick download's choices, as on its page: the quality list, Format and codec, and the Download button. */
export default function QuickDownloadForm({url, sourceKey, title, imageUrl, options, settings, waiting, onQueued}: QuickDownloadFormProps) {
    const defaults = useMemo(() => choiceFromSettings(settings), [settings])
    const rules = useMemo(() => rulesFromSettings(settings), [settings])
    const [choice, setChoice] = useState<QuickChoice>(defaults)
    const [initial, setInitial] = useState<QuickChoice>(defaults)
    const [panelOpen, setPanelOpen] = useState(false)
    const [sending, setSending] = useState(false)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!options) return
        const fitted = fitRules(fitChoice(defaults, options), options, rules)
        setChoice(fitted)
        setInitial(fitted)
    }, [options, defaults, rules])

    if (!options) {
        return (
            <div className="quick-lookup" aria-busy="true">
                <ol className="quick-lookup-steps">
                    <li className="is-active">
                        <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin/>
                        <span>Listing formats and sizes</span>
                    </li>
                </ol>
                <div className="quick-lookup-bar" aria-hidden="true"><span/></div>
            </div>
        )
    }
    if (options.refused) return <p className="form-error-card" role="alert">{options.refused}</p>

    const summary = choiceSummary(choice)
    const size = choiceSize(options, choice)
    const problem = waiting ? null : ruleProblem(options, choice, rules)
    const recommended = fitChoice(defaults, options).quality

    const download = async () => {
        setSending(true)
        setError(null)
        try {
            await sendQueueMessage({type: 'queue.add', download: {url, sourceKey, title, imageUrl, choice, summary}})
            onQueued()
        } catch (exc) {
            setError(messageOf(exc))
        } finally {
            setSending(false)
        }
    }

    return (
        <div className="extension-quick">
            {waiting && (
                <p className="quick-muted extension-note">
                    {waiting === 'vodloft'
                        ? 'The extension keeps the download and sends it to VODLoft as soon as VODLoft is back.'
                        : 'The extension keeps the download and sends it to VODLoft once you are signed in there.'}
                </p>
            )}
            <QuickOptionList options={options} choice={choice} recommended={recommended} rules={rules} onChange={setChoice}/>
            {problem && <p className="form-error-card" role="alert">{problem}</p>}
            {error && <p className="form-error-card" role="alert">{error}</p>}
            {rules.locked ? (
                <span className="quick-muted quick-locked-note">
                    <FontAwesomeIcon icon={faIcon('fass', 'lock')}/> <span>Set in Settings › Quick download</span>
                </span>
            ) : (
                <button type="button" className="quick-link-button" onClick={() => setPanelOpen(true)}>
                    <FontAwesomeIcon icon={faIcon('fass', 'sliders')}/>
                    <span>Format and codec</span>
                </button>
            )}
            <div className="quick-download-footer">
                <span className="quick-footer-choice" aria-hidden="true">
                    <strong>{summary}</strong>
                    <small>{sizeLabel(size) || 'size unknown'}</small>
                </span>
                <button type="button" className="btn btn-primary quick-download-button" disabled={!!problem || sending}
                        onClick={() => void download()}>
                    <FontAwesomeIcon icon={faIcon('fass', sending ? 'spinner' : 'download')} spin={sending}/>
                    <span className="quick-download-button-short">Download</span>
                </button>
            </div>
            {!rules.locked && (
                <QuickFormatPanel
                    open={panelOpen}
                    options={options}
                    sourceName={options.link?.source.name ?? 'This site'}
                    choice={choice}
                    initial={initial}
                    rules={rules}
                    saveAsDefaults={false}
                    onChange={setChoice}
                    onClose={() => setPanelOpen(false)}
                />
            )}
        </div>
    )
}
