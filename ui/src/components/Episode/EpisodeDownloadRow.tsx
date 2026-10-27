import {useState} from 'react'

import {isPublicationDelayWait} from '../../lib/downloadProgress'
import type {LocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import type {MediaDownloadViewRead} from '../../types/schemas/media_download'
import {faIcon} from '../../icons/faIcon'
import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {DownloadRow, useDownloadRowRequest} from '../MediaDownload/DownloadRow'
import {
    ImmediateSafeDelayConfirmDialog,
    SafeDelayConfirmDialog,
    freezeSafeDelaySchedulePreference,
    shouldPromptForSafeDelay,
} from './SafeDelayDownloadDialogs'

type SafeDelayAction = 'download' | 'retry'
type SafeDelayDialogState = {
    action: SafeDelayAction
    step: 'choice' | 'immediate'
}

export function EpisodeDownloadRow({
    profile,
    download,
    downloadStateKnown = true,
    episodeSlug,
    confirmCountdownDownload,
    confirmSafeDelayDownload,
    safeDelayReadyAt,
}: {
    profile: LocalMediaProfileRead
    download?: MediaDownloadViewRead
    downloadStateKnown?: boolean
    episodeSlug: string
    confirmCountdownDownload: boolean
    confirmSafeDelayDownload: boolean
    safeDelayReadyAt: Date | null
}) {
    const {busy, request, cancel} = useDownloadRowRequest(['episodeDownloads', episodeSlug])
    const [countdownConfirm, setCountdownConfirm] = useState(false)
    const [safeDelayDialog, setSafeDelayDialog] = useState<SafeDelayDialogState | null>(null)
    const [safeDelaySchedulePreferred, setSafeDelaySchedulePreferred] = useState<boolean | null>(null)
    const [safeDelaySubmitting, setSafeDelaySubmitting] = useState<'schedule' | 'immediate' | null>(null)
    const [redownloadWhenFinal, setRedownloadWhenFinal] = useState(true)
    const [redownloadWhenDelayPassed, setRedownloadWhenDelayPassed] = useState(true)

    const publicationDelayWait = Boolean(
        download
        && isPublicationDelayWait(download.operation)
    )
    const schedulePreferred = safeDelaySchedulePreferred === true
    const safeDelayIsRetry = safeDelayDialog?.action === 'retry'

    const startDownload = ({
        redownloadFinal = false,
        redownloadDelayPassed = false,
        scheduleForDelay = false,
    }: {
        redownloadFinal?: boolean
        redownloadDelayPassed?: boolean
        scheduleForDelay?: boolean
    } = {}) =>
        request(
            `/episodes/${encodeURIComponent(episodeSlug)}/downloads`,
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    localMediaProfileId: profile.id,
                    redownloadWhenFinal: redownloadFinal,
                    redownloadWhenDelayPassed: redownloadDelayPassed,
                    scheduleForDelay,
                }),
            },
            scheduleForDelay ? 'Could not schedule the download' : 'Could not start the download',
        )

    const retryDownload = ({
        redownloadDelayPassed = false,
        scheduleForDelay = false,
    }: {
        redownloadDelayPassed?: boolean
        scheduleForDelay?: boolean
    } = {}) =>
        request(
            `/media-downloads/${download!.id}/retry`,
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    redownloadWhenDelayPassed: redownloadDelayPassed,
                    scheduleForDelay,
                }),
            },
            scheduleForDelay ? 'Could not schedule the re-download' : 'Could not retry the download',
        )

    const closeSafeDelayDialogs = () => {
        setSafeDelayDialog(null)
    }

    const openSafeDelayDialog = (action: SafeDelayAction) => {
        // Freeze the primary action for this mounted row. Unrelated re-renders
        // must not swap buttons under the user as the ten-minute threshold passes.
        // A page reload remounts the row and recalculates the preference.
        setSafeDelaySchedulePreferred((current) => (
            freezeSafeDelaySchedulePreference(current, safeDelayReadyAt)
        ))
        setSafeDelayDialog({action, step: 'choice'})
    }

    const requestDownload = () => {
        if (confirmCountdownDownload) {
            setRedownloadWhenFinal(true)
            setCountdownConfirm(true)
            return
        }
        if (shouldPromptForSafeDelay(confirmSafeDelayDownload, safeDelayReadyAt)) {
            setRedownloadWhenDelayPassed(true)
            openSafeDelayDialog('download')
            return
        }
        void startDownload()
    }

    const requestRetry = () => {
        if (shouldPromptForSafeDelay(confirmSafeDelayDownload, safeDelayReadyAt)) {
            setRedownloadWhenDelayPassed(true)
            openSafeDelayDialog('retry')
            return
        }
        void retryDownload()
    }

    const scheduleSafeDelayDownload = async () => {
        setSafeDelaySubmitting('schedule')
        try {
            if (safeDelayDialog?.action === 'retry') {
                await retryDownload({scheduleForDelay: true})
            } else {
                await startDownload({scheduleForDelay: true})
            }
            closeSafeDelayDialogs()
        } finally {
            setSafeDelaySubmitting(null)
        }
    }

    const downloadImmediately = async () => {
        setSafeDelaySubmitting('immediate')
        try {
            if (safeDelayDialog?.action === 'retry') {
                await retryDownload({redownloadDelayPassed: redownloadWhenDelayPassed})
            } else {
                await startDownload({redownloadDelayPassed: redownloadWhenDelayPassed})
            }
            closeSafeDelayDialogs()
        } finally {
            setSafeDelaySubmitting(null)
        }
    }

    const requestImmediateSafeDelayDownload = () => {
        if (!schedulePreferred) {
            void downloadImmediately()
            return
        }
        setRedownloadWhenDelayPassed(true)
        setSafeDelayDialog((current) => (
            current ? {...current, step: 'immediate'} : current
        ))
    }

    const showRetryButton = Boolean(
        download
        && (
            (!download.presentation.active && download.presentation.canRetry)
            || publicationDelayWait
        )
    )

    const succeeded = download?.presentation.outcome === 'success'
    return (
        <DownloadRow
            profile={profile}
            download={download}
            downloadStateKnown={downloadStateKnown}
            busy={busy}
            retry={showRetryButton
                ? {
                    title: publicationDelayWait ? 'Download now' : succeeded ? 'Re-download' : 'Retry download',
                    label: publicationDelayWait
                        ? `Download ${profile.name} now`
                        : succeeded
                            ? `Re-download ${profile.name}`
                            : `Retry download for ${profile.name}`,
                    onClick: requestRetry,
                }
                : null}
            onDownload={requestDownload}
            onCancel={() => download && void cancel(download)}
        >
            <ConfirmDialog
                open={countdownConfirm}
                title="Download episode with countdown?"
                onDismiss={() => {
                    if (!busy) setCountdownConfirm(false)
                }}
                icon={faIcon('fass', 'circle-exclamation')}
                dismissOnOverlayClick={!busy}
                cancelButton={{disabled: busy}}
                confirmButton={{
                    label: busy ? 'Starting…' : 'Yes, download',
                    onClick: async () => {
                        await startDownload({redownloadFinal: redownloadWhenFinal})
                        setCountdownConfirm(false)
                    },
                    icon: faIcon('fass', 'download'),
                    disabled: busy,
                }}
            >
                <p>
                    This episode is published, but its current media still contains the countdown shown while it was live.
                </p>
                <p>
                    If you continue, VODLoft will download the current media as-is, including that countdown.
                </p>
                <label className="confirm-dialog-option">
                    <input
                        type="checkbox"
                        checked={redownloadWhenFinal}
                        onChange={(event) => setRedownloadWhenFinal(event.target.checked)}
                        disabled={busy}
                    />
                    <span>Re-download automatically when the countdown is gone</span>
                </label>
            </ConfirmDialog>
            <SafeDelayConfirmDialog
                open={safeDelayDialog?.step === 'choice'}
                isRetry={safeDelayIsRetry}
                safeDelayReadyAt={safeDelayReadyAt}
                schedulePreferred={schedulePreferred}
                busy={busy}
                submitting={safeDelaySubmitting}
                redownloadWhenDelayPassed={redownloadWhenDelayPassed}
                onRedownloadWhenDelayPassedChange={setRedownloadWhenDelayPassed}
                onDismiss={() => {
                    if (!busy) closeSafeDelayDialogs()
                }}
                onSchedule={scheduleSafeDelayDownload}
                onImmediate={requestImmediateSafeDelayDownload}
            />
            <ImmediateSafeDelayConfirmDialog
                open={safeDelayDialog?.step === 'immediate'}
                isRetry={safeDelayIsRetry}
                busy={busy}
                submitting={safeDelaySubmitting}
                redownloadWhenDelayPassed={redownloadWhenDelayPassed}
                onRedownloadWhenDelayPassedChange={setRedownloadWhenDelayPassed}
                onDismiss={() => {
                    if (!busy) closeSafeDelayDialogs()
                }}
                onImmediate={downloadImmediately}
            />
        </DownloadRow>
    )
}
