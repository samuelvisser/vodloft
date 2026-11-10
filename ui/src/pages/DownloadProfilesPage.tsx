import {useCallback, useMemo, useRef, useState} from 'react'
import {can} from '../lib/access'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import {type DownloadProfileTableFilters, useDownloadProfilesTable, useLocalMediaProfiles, useDownloadProfileSites} from '../lib/queries'
import ProfileTableFilters, {FORMAT_OPTIONS, STATUS_OPTIONS} from '../components/common/ProfileTableFilters'
import {ChipFilter} from '../components/common/FilterBar'
import SimpleSelect from '../components/common/SimpleSelect'
import {createSelectRegistry} from '../utils/selectRegistry'
import {updateLazyCollectionEntities} from '../lib/lazyCollection'
import LoadMore from '../components/common/LoadMore'
import {DownloadProfileReadView} from '../types/schemas/download_profile_view'
import {PreferredFormatReg} from '../types/local_media_profile'
import DataTable, {Column} from '../components/DataTable/DataTable'
import ConfirmDeleteDialog, {ConfirmDeleteDialogRef} from '../components/ConfirmDeleteDialog/ConfirmDeleteDialog'
import PageHeader from '../components/common/PageHeader'
import PageSubtitle from "../components/common/PageSubtitle";
import ProfileEnabledSwitch from '../components/common/ProfileEnabledSwitch'
import {DownloadProfileUpdateSchema} from '../types/schemas/download_profile'
import {faIcon} from '../icons/faIcon'
import {formatBytes} from '../utils/formatting'
import {apiUrl} from '../lib/api'
import {UpgradeRepeatReg} from '../types/schemas/siteSettings'
import {useBulkSelection} from '../components/ProfileBulkEdit/useBulkSelection'
import {ProfileTableActions, SelectAll} from '../components/ProfileBulkEdit/BulkEditControls'
import ProfileBulkEdit, {tableSelection} from '../components/ProfileBulkEdit/ProfileBulkEdit'
import type {BulkFieldSpec} from '../components/ProfileBulkEdit/BulkChangeDialog'

export default function DownloadProfilesPage() {
    const queryClient = useQueryClient()

    const [filters, setFilters] = useState<DownloadProfileTableFilters>({})
    const table = useDownloadProfilesTable(filters)
    const {data: sites} = useDownloadProfileSites()
    const siteOptions = (sites ?? []).map((site) => ({value: site.key, label: site.name}))
    const {data: mediaProfiles} = useLocalMediaProfiles()
    const MediaProfileReg = useMemo(() => {
        const collectionProfiles = (mediaProfiles ?? [])
            .filter((profile) => profile.type === 'collection')
            .sort((left, right) => left.name.localeCompare(right.name, undefined, {sensitivity: 'base', numeric: true}))
        const spec: Record<string, {label: string}> = {'': {label: 'All media profiles'}}
        for (const profile of collectionProfiles) spec[String(profile.id)] = {label: profile.name}
        return createSelectRegistry('DownloadProfileMediaProfileFilter', spec, ['', ...collectionProfiles.map((profile) => String(profile.id))])
    }, [mediaProfiles])
    const activeCount = [filters.site, filters.status, filters.format].filter((value) => value?.length).length
        + (filters.localMediaProfileId ? 1 : 0)
    const onSearch = useCallback((search: string) => setFilters((current) => ({...current, search})), [])

    const canManage = can('download_profiles', 'manage')
    const selection = useBulkSelection('downloadProfilesView', 'download-profiles/as-view', filters)
    const names = useMemo(
        () => new Map(table.items.map((profile) => [profile.id, `${profile.collectionTitle} (${profile.localMediaProfileName})`])),
        [table.items],
    )
    const bulkFields = useMemo<BulkFieldSpec[]>(() => {
        const ProfileReg = createSelectRegistry('BulkDownloadProfileMediaProfile', Object.fromEntries(
            MediaProfileReg.values.filter((value) => value).map((value) => [value, {label: MediaProfileReg.getLabel(value)}]),
        ), MediaProfileReg.values.filter((value) => value))
        return [
            {key: 'enableProfile', label: 'Enabled', kind: 'switch', defaultValue: true},
            {
                key: 'localMediaProfileId', label: 'Local Media Profile', kind: 'select', defaultValue: '',
                registry: ProfileReg, toApi: Number,
                valueLabel: (value) => ProfileReg.getLabelLoose(String(value)),
                help: 'Episodes downloaded before keep their files where they are.',
            },
            {key: 'downloadWithCountdown', label: 'Download with countdown', kind: 'switch', defaultValue: true},
            {key: 'upgradeCheck', label: 'Check for better versions', kind: 'switch', defaultValue: true},
            {key: 'upgradeRepeat', label: 'How often to check', kind: 'select', defaultValue: 'once', registry: UpgradeRepeatReg},
        ]
    }, [MediaProfileReg])

    const confirmRef = useRef<ConfirmDeleteDialogRef>(null)

    const setProfileEnabled = useCallback(async (profile: DownloadProfileReadView, enableProfile: boolean) => {
        try {
            const body = DownloadProfileUpdateSchema.parse({...profile, enableProfile})

            const response = await fetch(`${apiUrl()}/download-profiles/${profile.id}`, {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include',
                body: JSON.stringify(body),
            })
            if (!response.ok) throw new Error(`Failed to update download profile (${response.status})`)

            updateLazyCollectionEntities<DownloadProfileReadView>(queryClient, ['downloadProfilesView'], (item) => (
                item.id === profile.id ? {...item, enableProfile} : item
            ))

            await Promise.allSettled([
                queryClient.invalidateQueries({queryKey: ['downloadProfilesView']}),
                queryClient.invalidateQueries({queryKey: ['downloadProfilesByCollectionSlug']}),
            ])
        } catch (updateError) {
            toast.error(`Failed to ${enableProfile ? 'enable' : 'disable'} download profile`)
            throw updateError
        }
    }, [queryClient])

    const columns: Column<DownloadProfileReadView>[] = [
        {
            header: 'Collection Title',
            accessor: (p) => p.collectionTitle,
            mobileHidden: true,
        },
        {
            header: 'Local Media Profile',
            accessor: (p) => p.localMediaProfileName,
        },
        {
            header: 'Preferred Format',
            accessor: (p) => PreferredFormatReg.getLabelLoose(p.localMediaProfilePreferredFormat),
        },
        {
            header: 'Storage Used',
            accessor: (p) => formatBytes(p.storageSizeBytes) || '0 KiB',
            width: '1%',
            headerStyle: {whiteSpace: 'nowrap'},
            cellStyle: {whiteSpace: 'nowrap'},
        },
        {
            header: 'Enabled',
            cell: (p) => (
                <ProfileEnabledSwitch
                    checked={p.enableProfile}
                    ariaLabel={`Automatic downloads for ${p.collectionTitle}`}
                    onChange={(checked) => setProfileEnabled(p, checked)}
                />
            ),
            align: 'center',
        },
    ]

    return (
        <section className="view" aria-labelledby="profiles-title">
            <PageHeader
                title="Download Profiles"
                titleId="profiles-title"
                subtitle={(
                    <PageSubtitle summary={<>Create rules for how each collection is downloaded.</>}>
                        <p>A Download Profile tells VODLoft what to download and how long to retain your downloads.
                            Each collection can contain multiple download profiles, allowing you to
                            download both audio and video versions of episodes for example.</p>
                        <p>Download Profiles are always connected to a Local Media Profile, which defines where your
                            downloads will be stored and what their file name should be.</p>
                    </PageSubtitle>
                )}
                actions={canManage && <ProfileTableActions selection={selection} addTo="/add-download-profile" addLabel="Add download profile"/>}
            />

            <ProfileTableFilters
                search={filters.search ?? ''}
                onSearch={onSearch}
                searchPlaceholder="Search collections or media profiles"
                beside={(
                    <SimpleSelect
                        className="filter-bar-select"
                        aria-label="Filter by local media profile"
                        registry={MediaProfileReg}
                        value={filters.localMediaProfileId ? String(filters.localMediaProfileId) : ''}
                        onChange={(value) => setFilters((current) => ({...current, localMediaProfileId: value ? Number(value) : null}))}
                    />
                )}
                total={table.total}
                loading={table.isLoading}
                activeCount={activeCount}
                onReset={() => setFilters({})}
                leading={<SelectAll selection={selection} filtered={activeCount > 0 || !!filters.search}/>}
            >
                <ChipFilter label="Site" options={siteOptions} selected={filters.site ?? []} onChange={(site) => setFilters((current) => ({...current, site}))}/>
                <ChipFilter label="Status" options={STATUS_OPTIONS} selected={filters.status ?? []} onChange={(status) => setFilters((current) => ({...current, status}))}/>
                <ChipFilter label="Format" options={FORMAT_OPTIONS} selected={filters.format ?? []} onChange={(format) => setFilters((current) => ({...current, format}))}/>
            </ProfileTableFilters>

            <div className="form-row">
                <DataTable<DownloadProfileReadView>
                    ariaLabel="Existing download profiles"
                    columns={columns}
                    data={table.isLoading ? undefined : table.items}
                    loading={table.isLoading}
                    error={table.error}
                    rowKey={(p) => String(p.id)}
                    selection={tableSelection(selection)}
                    rowAriaLabel={(p) => p.collectionTitle}
                    mobileSummary={(p) => (
                        <>
                            <span className="mobile-summary-title">{p.collectionTitle}</span>
                            <span className="mobile-summary-meta">
                                <span>{p.localMediaProfileName}</span>
                                <span aria-hidden="true">•</span>
                                <span>{PreferredFormatReg.getLabelLoose(p.localMediaProfilePreferredFormat)}</span>
                                <span aria-hidden="true">•</span>
                                <span>{formatBytes(p.storageSizeBytes) || '0 KiB'}</span>
                                <span className={`mobile-summary-status ${p.enableProfile ? 'is-success' : ''}`}>
                                    {p.enableProfile ? 'Enabled' : 'Disabled'}
                                </span>
                            </span>
                        </>
                    )}
                    rowHref={(p) => `/edit-download-profile/${p.id}`}
                    actions={(p) => [
                        {
                            href: `/edit-download-profile/${p.id}`,
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
                endpoint="download-profiles"
                noun={['download profile', 'download profiles']}
                names={names}
                fields={bulkFields}
                canEnable
                deleteNote="Their downloaded files stay where they are."
                invalidate={[['downloadProfilesView'], ['downloadProfilesByCollectionSlug']]}
            />

            <ConfirmDeleteDialog
                ref={confirmRef}
                title="Delete download profile"
                subjectProp="collectionTitle"
                deleteRequest={(p) => fetch(
                    `${apiUrl()}/download-profiles/${p.id}`,
                    {method: 'DELETE', credentials: 'include'},
                )}
                invalidateQueries={[["downloadProfilesView"], ["downloadProfilesByCollectionSlug"]]}
                inUseMessage="This download profile is in use, it cannot be deleted"
            />
        </section>
    )
}
