import {useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link, useNavigate, useParams} from 'react-router-dom'
import toast from 'react-hot-toast'

import ActionMenu from '../../components/ActionMenu/ActionMenu'
import ConfirmDeleteDialog, {ConfirmDeleteDialogRef} from '../../components/ConfirmDeleteDialog/ConfirmDeleteDialog'
import OutOfScopeDownloadsDialog, {mayDeleteOutOfScope} from '../../components/DownloadProfile/OutOfScopeDownloadsDialog'
import {filterSentence, plainText} from '../../components/DownloadProfile/whichEpisodesText'
import {useActiveOperation} from '../../components/OperationNotifier/OperationNotifier'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {apiUrl} from '../../lib/api'
import {OperationControlError, useControlOperation, useStartingOperations} from '../../lib/operations'
import {
    useCollectionSeasons, useDownloadProfileOutOfScope, useDownloadProfileStatistics, useDownloadProfileView,
    useEpisodeTagsInCollection, useLocalMediaProfiles,
} from '../../lib/queries'
import type {DownloadProfileRead} from '../../types/schemas/download_profile'
import {PreferredFormatReg} from '../../types/local_media_profile'
import {formatBytes} from '../../utils/formatting'
import '../local-media-profile/LocalMediaProfilePage.css'

const OPERATION_KIND = 'download_profile.delete_out_of_scope'

/** A Download Profile's page: what it downloads, how much, and its actions. */
export default function DownloadProfilePage() {
    const {id} = useParams<{id: string}>()
    const profileId = id ? Number(id) : undefined
    const navigate = useNavigate()
    const {data: profile, isLoading, error} = useDownloadProfileView(profileId)
    const {data: statistics, error: statisticsError, refetch: refetchStatistics, isFetching: counting} = useDownloadProfileStatistics(profileId)
    const {data: localMediaProfiles} = useLocalMediaProfiles()
    const {data: seasons} = useCollectionSeasons(profile?.collectionSlug)
    const {data: tags} = useEpisodeTagsInCollection(profile?.collectionSlug)
    const [outOfScopeOpen, setOutOfScopeOpen] = useState(false)
    const {data: outOfScope} = useDownloadProfileOutOfScope(profileId, outOfScopeOpen)
    const {isStarting, onStartingChange} = useStartingOperations()
    const controlOperation = useControlOperation()
    const [controlBusy, setControlBusy] = useState(false)
    const deleteRef = useRef<ConfirmDeleteDialogRef>(null)
    const operation = useActiveOperation(OPERATION_KIND, 'download_profile', profileId ?? null)
    const canManage = can('download_profiles', 'manage')

    if (isLoading) {
        return (
            <section className="view local-media-profile-view" aria-labelledby="download-profile-title">
                <div className="view-header"><h1 id="download-profile-title">Download Profile</h1></div>
                <p>Loading…</p>
            </section>
        )
    }
    if (!profileId || !profile || error) {
        return (
            <section className="view local-media-profile-view" aria-labelledby="download-profile-title">
                <div className="view-header"><h1 id="download-profile-title">Download Profile</h1></div>
                <p role="alert">This Download Profile could not be loaded.</p>
            </section>
        )
    }

    const resourceLabel = `${profile.collectionTitle} (${profile.localMediaProfileName})`
    const localMediaProfile = localMediaProfiles?.find((item) => item.id === profile.localMediaProfileId)
    const typeLabel = (key: string) => tags?.find((tag) => tag.key === key)?.label ?? key
    const seasonLabel = (slug: string) => seasons?.find((season) => season.slug === slug)?.name ?? slug
    const sentence = (filter: DownloadProfileRead['filters'][number]) => plainText(
        filterSentence(filter, typeLabel, seasonLabel, profile.deleteOlderEpisodes),
    )
    const filterText = (index: number) => {
        const filter = profile.filters[index]
        return filter ? `Left out by: ${sentence(filter).replace(/^\w/, (c) => c.toLowerCase())}` : ''
    }
    const outside = statistics ? statistics.outOfScope + statistics.outOfScopeKept : 0
    // Counting walks the filters over every episode of the Collection, which takes a while on a busy server.
    const counted = (value: number | string | undefined) => value !== undefined ? value : (
        <span className="download-profile-stat-counting">
            <FontAwesomeIcon icon={faIcon('fass', 'circle-notch')} spin aria-hidden="true"/>
            <span>{statisticsError && !counting ? 'Not counted' : 'Counting…'}</span>
        </span>
    )

    const control = async (action: 'cancel') => {
        if (!operation || controlBusy) return
        setControlBusy(true)
        try {
            await controlOperation(operation.id, action)
            toast.success('Deleting downloads canceled')
        } catch (controlError) {
            const detail = controlError instanceof OperationControlError ? controlError.message : undefined
            toast.error(`Could not cancel deleting downloads${detail ? `: ${detail}` : ''}`)
        } finally {
            setControlBusy(false)
        }
    }

    return (
        <section className="view local-media-profile-view" aria-labelledby="download-profile-title">
            <div className="view-header">
                <h1 id="download-profile-title">{profile.collectionTitle}</h1>
            </div>

            <article className="local-media-profile-details" aria-label="Download Profile details">
                <header className="local-media-profile-page-header">
                    <div className="local-media-profile-page-heading">
                        <div className="local-media-profile-kind">Download Profile</div>
                        <div className="local-media-profile-meta">
                            {profile.localMediaProfileName} · {PreferredFormatReg.getLabelLoose(profile.localMediaProfilePreferredFormat)}
                            {' · '}{profile.enableProfile ? 'Enabled' : 'Disabled'}
                        </div>
                    </div>

                    {canManage && (
                        <div className="local-media-profile-page-actions">
                            <Link className="btn" to={`/edit-download-profile/${profile.id}`}>
                                <FontAwesomeIcon icon={faIcon('fass', 'pen-to-square')} aria-hidden="true"/>
                                <span>Edit</span>
                            </Link>
                            <button type="button" className="btn btn-danger" onClick={() => deleteRef.current?.open(profile)}>
                                <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/>
                                <span>Delete</span>
                            </button>
                            <ActionMenu
                                items={[
                                    {
                                        label: 'Delete downloads outside its filters',
                                        icon: faIcon('fass', 'trash'),
                                        tone: 'danger',
                                        disabled: Boolean(operation) || outside === 0 || !mayDeleteOutOfScope(),
                                        disabledReason: !mayDeleteOutOfScope()
                                            ? 'You may not delete downloaded files.'
                                            : operation
                                            ? 'Downloads outside its filters are being deleted.'
                                            : !statistics
                                                ? 'Still counting its downloads.'
                                            : outside === 0
                                                ? 'Its filters cover every download it has.'
                                                : undefined,
                                        operation,
                                        starting: isStarting(OPERATION_KIND),
                                        controls: operation ? [{
                                            label: 'Cancel deleting downloads',
                                            icon: faIcon('fass', 'xmark'),
                                            tone: 'danger' as const,
                                            disabled: controlBusy,
                                            onSelect: () => void control('cancel'),
                                        }] : undefined,
                                        onSelect: () => setOutOfScopeOpen(true),
                                    },
                                ]}
                            />
                        </div>
                    )}
                </header>

                {statisticsError && !counting && (
                    <div className="form-error-card" role="alert">
                        Could not count this profile's downloads ({statisticsError.message}).{' '}
                        <button type="button" className="btn" onClick={() => void refetchStatistics()}>Try again</button>
                    </div>
                )}
                <div className="local-media-profile-statistics" aria-label="Profile statistics" aria-busy={!statistics}>
                    <div className="local-media-profile-stat">
                        <span className="local-media-profile-stat-value">{counted(statistics?.wanted)}</span>
                        <span className="local-media-profile-stat-label">Episodes it downloads</span>
                    </div>
                    <div className="local-media-profile-stat">
                        <span className="local-media-profile-stat-value">{counted(statistics?.downloaded)}</span>
                        <span className="local-media-profile-stat-label">Downloaded episodes</span>
                    </div>
                    <div className="local-media-profile-stat">
                        <span className="local-media-profile-stat-value">
                            {formatBytes(statistics?.storageSizeBytes ?? profile.storageSizeBytes) || '0 KiB'}
                        </span>
                        <span className="local-media-profile-stat-label">Storage used</span>
                    </div>
                    <div className="local-media-profile-stat">
                        <span className="local-media-profile-stat-value">{counted(statistics ? outside : undefined)}</span>
                        <span className="local-media-profile-stat-label">
                            Outside its filters{statistics?.outOfScopeKept ? `, ${statistics.outOfScopeKept} kept` : ''}
                        </span>
                    </div>
                </div>

                <dl className="local-media-profile-properties">
                    <div>
                        <dt>Collection</dt>
                        <dd><Link className="quiet-link" to={`/collection/${profile.collectionSlug}`}>{profile.collectionTitle}</Link></dd>
                    </div>
                    <div>
                        <dt>Local Media Profile</dt>
                        <dd>
                            {localMediaProfile && can('local_media_profiles')
                                ? <Link className="quiet-link" to={`/local-media-profile/${encodeURIComponent(localMediaProfile.slug)}`}>{profile.localMediaProfileName}</Link>
                                : profile.localMediaProfileName}
                        </dd>
                    </div>
                    <div>
                        <dt>Which episodes</dt>
                        <dd>
                            {profile.filters.length ? (
                                <ol className="download-profile-filter-list">
                                    {profile.filters.map((filter) => <li key={filter.id}>{sentence(filter)}</li>)}
                                </ol>
                            ) : 'Every episode'}
                        </dd>
                    </div>
                    <div>
                        <dt>Delete older episodes</dt>
                        <dd>{profile.deleteOlderEpisodes ? 'Yes, when a date line leaves them out' : 'No'}</dd>
                    </div>
                </dl>
            </article>

            <OutOfScopeDownloadsDialog
                open={outOfScopeOpen}
                profileId={profile.id}
                collectionSlug={profile.collectionSlug}
                resourceLabel={resourceLabel}
                downloads={outOfScope}
                filterText={filterText}
                onDismiss={() => setOutOfScopeOpen(false)}
                onStartingChange={onStartingChange(OPERATION_KIND)}
            />

            <ConfirmDeleteDialog
                ref={deleteRef}
                title="Delete download profile"
                subjectProp="collectionTitle"
                deleteRequest={() => fetch(`${apiUrl()}/download-profiles/${profile.id}`, {method: 'DELETE', credentials: 'include'})}
                invalidateQueries={[['downloadProfilesView'], ['downloadProfilesByCollectionSlug']]}
                inUseMessage="This download profile is in use, it cannot be deleted"
                deletedMessage={(p) => `Deleted the Download Profile of ${p.collectionTitle}`}
                onDeleted={() => navigate('/download-profiles')}
            />
        </section>
    )
}
