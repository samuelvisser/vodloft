import {useCallback, useRef} from 'react'
import {can} from '../lib/access'
import {Link} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import {useStreamProfilesView} from '../lib/queries'
import {StreamProfileReadView} from '../types/schemas/stream_profile_base'
import DataTable, {Column} from '../components/DataTable/DataTable'
import ConfirmDeleteDialog, {ConfirmDeleteDialogRef} from '../components/ConfirmDeleteDialog/ConfirmDeleteDialog'
import {PreferredFormatReg} from "../types/local_media_profile";
import PageSubtitle from "../components/common/PageSubtitle";
import ProfileEnabledSwitch from '../components/common/ProfileEnabledSwitch'
import {RssStreamProfileUpdateSchema} from '../types/schemas/rss_stream_profile'
import {faIcon} from '../icons/faIcon'

export default function StreamProfilesPage() {
    const queryClient = useQueryClient()

    const {data: profiles, isLoading, error} = useStreamProfilesView()

    const confirmRef = useRef<ConfirmDeleteDialogRef>(null)

    const setProfileEnabled = useCallback(async (profile: StreamProfileReadView, enableProfile: boolean) => {
        try {
            const body = RssStreamProfileUpdateSchema.parse({
                ...profile.streamProfileImpl,
                title: profile.streamProfileImpl.effectiveTitle,
                enableProfile,
            })
            const response = await fetch(`${(window as any).appConfig.API_URL}/rss-stream-profiles/${profile.id}`, {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include',
                body: JSON.stringify(body),
            })
            if (!response.ok) throw new Error(`Failed to update stream profile (${response.status})`)

            queryClient.setQueryData<StreamProfileReadView[]>(['streamProfilesView'], (current) => (
                current?.map((item) => (
                    item.id === profile.id && item.type === profile.type
                        ? {...item, enableProfile}
                        : item
                ))
            ))

            await Promise.allSettled([
                queryClient.invalidateQueries({queryKey: ['streamProfilesView']}),
                queryClient.invalidateQueries({queryKey: ['rssStreamProfiles']}),
            ])
        } catch (updateError) {
            toast.error(`Failed to ${enableProfile ? 'enable' : 'disable'} stream profile`)
            throw updateError
        }
    }, [queryClient])

    const columns: Column<StreamProfileReadView>[] = [
        {
            header: 'Title',
            accessor: (p) => p.streamProfileImpl.effectiveTitle,
            mobileHidden: true,
        },
        {
            header: 'Preferred Format',
            accessor: (p) => PreferredFormatReg.getLabelLoose(p.preferredFormat),
        },
        {
            header: 'Type',
            accessor: (p) => p.type,
        },
        {
            header: 'Stream Downloads',
            accessor: (p) => (p.useDownloads ? '✓' : '✕'),
            align: 'center',
        },
        {
            header: 'Stream from DW',
            accessor: (p) => (p.useSourceStream ? '✓' : '✕'),
            align: 'center',
        },
        {
            header: 'Enabled',
            cell: (p) => (
                <ProfileEnabledSwitch
                    checked={p.enableProfile}
                    ariaLabel={`Stream profile for ${p.streamProfileImpl.effectiveTitle}`}
                    onChange={(checked) => setProfileEnabled(p, checked)}
                />
            ),
            align: 'center',
        },
    ]

    return (
        <section className="view" aria-labelledby="stream-profiles-title">
            <div className="view-header">
                <h1 id="stream-profiles-title">Stream Profiles</h1>
                <PageSubtitle summary={<>Control how VODLoft streams each collection.</>}>
                    <p>Stream Profiles allow you to control how each collection is streamed. You can stream episodes straight from the files
                        you downloaded, or directly from DW. </p>
                    <p>For now, a stream within VODLoft just means opening an RSS feed for it. More streaming options might come later.</p>
                    <p>Use multiple profiles per collection to fit different listening or
                        viewing needs.</p>
                </PageSubtitle>
                {can('stream_profiles') && <Link className="btn btn-primary" to="/add-stream-profile">Add stream profile</Link>}
            </div>

            <div className="form-row">
                <DataTable<StreamProfileReadView>
                    ariaLabel="Existing stream profiles"
                    columns={columns}
                    data={profiles}
                    loading={isLoading}
                    error={error}
                    rowKey={(p) => `${p.type}-${p.id}`}
                    rowAriaLabel={(p) => `${p.type} ${p.streamProfileImpl.effectiveTitle}`}
                    mobileSummary={(p) => (
                        <>
                            <span className="mobile-summary-title">{p.streamProfileImpl.effectiveTitle}</span>
                            <span className="mobile-summary-meta">
                                <span>{PreferredFormatReg.getLabelLoose(p.preferredFormat)}</span>
                                <span aria-hidden="true">•</span>
                                <span>{p.type}</span>
                                <span className={`mobile-summary-status ${p.enableProfile ? 'is-success' : ''}`}>
                                    {p.enableProfile ? 'Enabled' : 'Disabled'}
                                </span>
                            </span>
                        </>
                    )}
                    rowHref={(p) => `/edit-stream-profile/${p.type}/${p.id}`}
                    actions={(p) => [
                        {
                            href: `/edit-stream-profile/${p.type}/${p.id}`,
                            icon: faIcon('fass', 'pen-to-square'),
                            text: 'Edit',
                            classes: 'btn',
                        },
                        {
                            onClick: () => confirmRef.current?.open(p),
                            icon: faIcon('fass', 'trash'),
                            text: 'Delete',
                            classes: 'btn btn-danger',
                        },
                    ]}
                />
            </div>

            <ConfirmDeleteDialog
                ref={confirmRef}
                title="Delete stream profile"
                subjectProp="collectionTitle"
                deleteRequest={(p) => {
                    const path = `${p.type === 'rss' ? 'rss-stream-profiles' : 'stream-profiles'}/${p.id}`
                    return fetch(`${(window as any).appConfig.API_URL}/${path}`, {method: 'DELETE', credentials: 'include'})
                }}
                invalidateQueries={[["streamProfilesView"], ["rssStreamProfiles"]]}
                inUseMessage="This stream profile is in use, it cannot be deleted"
            />
        </section>
    )
}
