import {useCallback, useMemo, useRef, useState} from 'react'
import {can} from '../lib/access'
import {Link} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import {type StreamProfileTableFilters, useSources, useStreamProfilesTable} from '../lib/queries'
import ProfileTableFilters, {ChipFilter, FORMAT_OPTIONS, STATUS_OPTIONS} from '../components/common/ProfileTableFilters'
import {updateLazyCollectionEntities} from '../lib/lazyCollection'
import LoadMore from '../components/common/LoadMore'
import {StreamProfileReadView} from '../types/schemas/stream_profile_base'
import DataTable, {Column} from '../components/DataTable/DataTable'
import ConfirmDeleteDialog, {ConfirmDeleteDialogRef} from '../components/ConfirmDeleteDialog/ConfirmDeleteDialog'
import {PreferredFormatReg} from "../types/local_media_profile";
import PageSubtitle from "../components/common/PageSubtitle";
import ProfileEnabledSwitch from '../components/common/ProfileEnabledSwitch'
import {RssStreamProfileUpdateSchema} from '../types/schemas/rss_stream_profile'
import {faIcon} from '../icons/faIcon'
import {apiUrl} from '../lib/api'
import {useBulkSelection} from '../components/ProfileBulkEdit/useBulkSelection'
import {BulkEditButton, SelectAll} from '../components/ProfileBulkEdit/BulkEditControls'
import ProfileBulkEdit, {tableSelection} from '../components/ProfileBulkEdit/ProfileBulkEdit'
import type {BulkFieldSpec} from '../components/ProfileBulkEdit/BulkChangeDialog'

const BULK_FIELDS: BulkFieldSpec[] = [
    {key: 'enableProfile', label: 'Enabled', kind: 'switch', defaultValue: true},
    {key: 'useDownloads', label: 'Stream downloads', kind: 'switch', defaultValue: true},
    {key: 'useSourceStream', label: 'Stream directly from the site', kind: 'switch', defaultValue: true},
    {key: 'maxItems', label: 'Episodes in the feed', kind: 'number', defaultValue: 100, min: 0, help: '0 puts every episode in the feed.'},
    {key: 'proxySourceStream', label: 'Stream through VODLoft', kind: 'switch', defaultValue: true},
    {key: 'streamLiveEpisodes', label: 'Live episodes', kind: 'switch', defaultValue: true},
]

const STREAMS_FROM_OPTIONS = [
    {value: 'downloads', label: 'Downloads'},
    {value: 'source', label: 'Direct from Site'},
]

export default function StreamProfilesPage() {
    const queryClient = useQueryClient()

    const [filters, setFilters] = useState<StreamProfileTableFilters>({})
    const table = useStreamProfilesTable(filters)
    const {data: sources} = useSources()
    const sourceOptions = (sources ?? [])
        .filter((source) => source.features.includes('collections'))
        .map((source) => ({value: source.id, label: source.name}))
    const activeCount = [filters.source, filters.status, filters.streamsFrom, filters.format].filter((value) => value?.length).length
    const onSearch = useCallback((search: string) => setFilters((current) => ({...current, search})), [])

    const canManage = can('stream_profiles')
    const selection = useBulkSelection('streamProfilesView', 'stream-profiles/as-view', filters)
    const names = useMemo(
        () => new Map(table.items.map((profile) => [profile.id, profile.streamProfileImpl.effectiveTitle])),
        [table.items],
    )

    const confirmRef = useRef<ConfirmDeleteDialogRef>(null)

    const setProfileEnabled = useCallback(async (profile: StreamProfileReadView, enableProfile: boolean) => {
        try {
            const body = RssStreamProfileUpdateSchema.parse({
                ...profile.streamProfileImpl,
                title: profile.streamProfileImpl.effectiveTitle,
                enableProfile,
            })
            const response = await fetch(`${apiUrl()}/rss-stream-profiles/${profile.id}`, {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include',
                body: JSON.stringify(body),
            })
            if (!response.ok) throw new Error(`Failed to update stream profile (${response.status})`)

            updateLazyCollectionEntities<StreamProfileReadView>(queryClient, ['streamProfilesView'], (item) => (
                item.id === profile.id && item.type === profile.type ? {...item, enableProfile} : item
            ))

            await queryClient.invalidateQueries({queryKey: ['streamProfilesView']})
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
            header: 'Direct from Site',
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
                {canManage && <BulkEditButton selection={selection}/>}
                {canManage && <Link className="btn btn-primary" to="/add-stream-profile">Add stream profile</Link>}
            </div>

            <ProfileTableFilters
                search={filters.search ?? ''}
                onSearch={onSearch}
                searchPlaceholder="Search stream profiles"
                total={table.total}
                loading={table.isLoading}
                activeCount={activeCount}
                onReset={() => setFilters({})}
                leading={<SelectAll selection={selection} filtered={activeCount > 0 || !!filters.search}/>}
            >
                <ChipFilter label="Source" options={sourceOptions} selected={filters.source ?? []} onChange={(source) => setFilters((current) => ({...current, source}))}/>
                <ChipFilter label="Status" options={STATUS_OPTIONS} selected={filters.status ?? []} onChange={(status) => setFilters((current) => ({...current, status}))}/>
                <ChipFilter label="Streams from" options={STREAMS_FROM_OPTIONS} selected={filters.streamsFrom ?? []} onChange={(streamsFrom) => setFilters((current) => ({...current, streamsFrom}))}/>
                <ChipFilter label="Format" options={FORMAT_OPTIONS} selected={filters.format ?? []} onChange={(format) => setFilters((current) => ({...current, format}))}/>
            </ProfileTableFilters>

            <div className="form-row">
                <DataTable<StreamProfileReadView>
                    ariaLabel="Existing stream profiles"
                    columns={columns}
                    data={table.isLoading ? undefined : table.items}
                    loading={table.isLoading}
                    error={table.error}
                    rowKey={(p) => p.id}
                    selection={tableSelection(selection)}
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
                <LoadMore {...table} noun="profiles"/>
            </div>

            <ProfileBulkEdit
                selection={selection}
                endpoint="stream-profiles"
                noun={['stream profile', 'stream profiles']}
                names={names}
                fields={BULK_FIELDS}
                canEnable
                deleteNote="Their feed links stop working."
                invalidate={[['streamProfilesView']]}
            />

            <ConfirmDeleteDialog
                ref={confirmRef}
                title="Delete stream profile"
                subjectProp="collectionTitle"
                deleteRequest={(p) => {
                    const path = `${p.type === 'rss' ? 'rss-stream-profiles' : 'stream-profiles'}/${p.id}`
                    return fetch(`${apiUrl()}/${path}`, {method: 'DELETE', credentials: 'include'})
                }}
                invalidateQueries={[["streamProfilesView"]]}
                inUseMessage="This stream profile is in use, it cannot be deleted"
            />
        </section>
    )
}
