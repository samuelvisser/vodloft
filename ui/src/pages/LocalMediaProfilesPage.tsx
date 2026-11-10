import {useCallback, useMemo, useRef, useState} from 'react'
import {can} from '../lib/access'
import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {type LocalMediaProfileTableFilters, type LocalMediaProfileTableRow, useLocalMediaProfilesTable} from '../lib/queries'
import ProfileTableFilters, {FORMAT_OPTIONS} from '../components/common/ProfileTableFilters'
import {ChipFilter} from '../components/common/FilterBar'
import LoadMore from '../components/common/LoadMore'
import {LocalMediaProfileRead} from "../types/schemas/local_media_profile";
import {formatBytes} from '../utils/formatting'
import {
    LocalMediaProfileTypeReg,
    PreferredFormatReg,
    CollectionLocalMediaProfileScopeReg,
} from "../types/local_media_profile";
import {faIcon} from '../icons/faIcon'
import DataTable, { Column } from '../components/DataTable/DataTable';
import ConfirmDeleteDialog, { ConfirmDeleteDialogRef } from '../components/ConfirmDeleteDialog/ConfirmDeleteDialog'
import PageHeader from '../components/common/PageHeader'
import PageSubtitle from "../components/common/PageSubtitle";
import OpaqueOutputTemplateCode from '../components/LocalMediaProfile/OpaqueOutputTemplateCode'
import {localMediaProfileEndpoint} from '../types/local_media_profile'
import './LocalMediaProfilesPage.css'
import {apiUrl} from '../lib/api'
import {createSelectRegistry} from '../utils/selectRegistry'
import {useBulkSelection} from '../components/ProfileBulkEdit/useBulkSelection'
import {ProfileTableActions, SelectAll} from '../components/ProfileBulkEdit/BulkEditControls'
import ProfileBulkEdit, {tableSelection} from '../components/ProfileBulkEdit/ProfileBulkEdit'
import type {BulkFieldSpec} from '../components/ProfileBulkEdit/BulkChangeDialog'

const USED_FOR_OPTIONS = [
    {value: 'podcast', label: 'Podcasts'},
    {value: 'series', label: 'Series'},
    {value: 'movie', label: 'Movies'},
    {value: 'video', label: 'Videos'},
]

const STORAGE_OPTIONS = [
    {value: 'files', label: 'Has files'},
    {value: 'empty', label: 'Empty'},
]

const BULK_FIELDS: BulkFieldSpec[] = [
    {
        key: 'downloadMode', label: 'Where downloads are saved first', kind: 'select', defaultValue: 'system',
        registry: createSelectRegistry('BulkLocalMediaProfileDownloadMode', {
            system: {label: 'System setting'},
            direct: {label: 'Save directly to downloads'},
            temporary: {label: 'Save to temporary folder first'},
        }),
    },
    {
        key: 'thumbnailMode', label: 'Thumbnails', kind: 'select', defaultValue: 'system',
        registry: createSelectRegistry('BulkLocalMediaProfileThumbnailMode', {
            system: {label: 'System setting'},
            no_thumbnail: {label: 'No thumbnail'},
            embed: {label: 'Embed in media'},
            sidecar: {label: 'Download besides media'},
            embed_and_sidecar: {label: 'Both embed and download'},
        }),
        help: 'Files downloaded before keep their thumbnails as they are.',
    },
    {
        key: 'metadataMode', label: 'Metadata', kind: 'select', defaultValue: 'system',
        registry: createSelectRegistry('BulkLocalMediaProfileMetadataMode', {
            system: {label: 'System setting'},
            no_metadata: {label: 'No metadata'},
            embed: {label: 'Embed in media'},
            nfo: {label: 'Download as NFO'},
            embed_and_nfo: {label: 'Both embed and download'},
        }),
        help: 'Files downloaded before keep their metadata as it is.',
    },
]

function getAvailableForLabel(profile: LocalMediaProfileRead) {
    return profile.type === 'collection'
        ? CollectionLocalMediaProfileScopeReg.getLabelLoose(profile.collectionScope)
        : 'Movies'
}

export default function LocalMediaProfilesPage() {
    const editIcon: IconProp = faIcon('fass', 'pen-to-square')
    const duplicateIcon: IconProp = faIcon('fass', 'copy')
    const deleteIcon: IconProp = faIcon('fass', 'trash')

    const confirmRef = useRef<ConfirmDeleteDialogRef>(null)

    const columns: Column<LocalMediaProfileTableRow>[] = [
        {
            header: 'Name',
            cell: (p) => (
                <span className="local-media-profile-name" title={p.name}>
                    {p.name}
                </span>
            ),
            width: '1%',
            headerStyle: {minWidth: 180, maxWidth: '30%', whiteSpace: 'nowrap'},
            cellStyle: {minWidth: 180, maxWidth: '30%', whiteSpace: 'nowrap', overflow: 'hidden'},
            mobileHidden: true,
        },
        {
            header: 'Output Path Template',
            cell: (p) => (
                <OpaqueOutputTemplateCode
                    source={p.outputTemplate}
                    sourceMode="compact"
                    renderMode="path"
                    label={`Output path template for ${p.name}`}
                    className="local-media-profile-output-template"
                />
            ),
            width: '100%',
            cellStyle: {maxWidth: 0},
        },
        {
            header: 'Type',
            accessor: (p) => LocalMediaProfileTypeReg.getLabelLoose(p.type),
            width: 90,
        },
        {
            header: 'Available for',
            accessor: getAvailableForLabel,
            width: '1%',
            headerStyle: {whiteSpace: 'nowrap'},
            cellStyle: {whiteSpace: 'nowrap'},
        },
        {
            header: 'Storage Used',
            accessor: (p) => formatBytes(p.storageSizeBytes) || '0 KiB',
            width: '1%',
            headerStyle: {whiteSpace: 'nowrap'},
            cellStyle: {whiteSpace: 'nowrap'},
        },
        {
            header: 'Preferred Format',
            accessor: (p) => PreferredFormatReg.getLabelLoose(p.preferredFormat),
            width: '1%',
            headerStyle: {whiteSpace: 'nowrap'},
            cellStyle: {whiteSpace: 'nowrap'},
        }
    ]

    const [filters, setFilters] = useState<LocalMediaProfileTableFilters>({})
    const table = useLocalMediaProfilesTable(filters)
    const activeCount = [filters.usedFor, filters.format, filters.storage].filter((value) => value?.length).length
    const onSearch = useCallback((search: string) => setFilters((current) => ({...current, search})), [])

    const canManage = can('local_media_profiles', 'manage')
    const selection = useBulkSelection('localMediaProfilesView', 'local-media-profiles/as-view', filters)
    const names = useMemo(() => new Map(table.items.map((profile) => [profile.id, profile.name])), [table.items])

    return (
        <section className="view" aria-labelledby="profiles-title">
            <PageHeader
                title="Local Media Profiles"
                titleId="profiles-title"
                subtitle={(
                    <PageSubtitle summary={<>Define how downloaded files are stored and in what format.</>}>
                        <p>A Local Media Profile controls the output path and the preferred file format for your downloads
                            across collections and movies. You can create multiple profiles (e.g., “Podcasts to ABS”, “Videos to NAS”) and
                            reuse them.</p>
                    </PageSubtitle>
                )}
                actions={canManage && <ProfileTableActions selection={selection} addTo="/add-local-media-profile" addLabel="Add media profile"/>}
            />

            <ProfileTableFilters
                search={filters.search ?? ''}
                onSearch={onSearch}
                searchPlaceholder="Search names or output paths"
                total={table.total}
                loading={table.isLoading}
                activeCount={activeCount}
                onReset={() => setFilters({})}
                leading={<SelectAll selection={selection} filtered={activeCount > 0 || !!filters.search}/>}
            >
                <ChipFilter label="Used for" options={USED_FOR_OPTIONS} selected={filters.usedFor ?? []} onChange={(usedFor) => setFilters((current) => ({...current, usedFor}))}/>
                <ChipFilter label="Format" options={FORMAT_OPTIONS} selected={filters.format ?? []} onChange={(format) => setFilters((current) => ({...current, format}))}/>
                <ChipFilter label="Storage" options={STORAGE_OPTIONS} selected={filters.storage ?? []} onChange={(storage) => setFilters((current) => ({...current, storage}))}/>
            </ProfileTableFilters>

            <div className="form-row">
                <DataTable<LocalMediaProfileTableRow>
                    ariaLabel="Existing media profiles"
                    columns={columns}
                    data={table.isLoading ? undefined : table.items}
                    loading={table.isLoading}
                    error={table.error}
                    rowKey={(p) => p.id}
                    selection={tableSelection(selection)}
                    rowAriaLabel={(p) => p.name}
                    className="table local-media-profiles-table"
                    wrapperClassName="table-wrapper local-media-profiles-table-wrapper"
                    mobileSummary={(p) => (
                        <>
                            <span className="mobile-summary-title">{p.name}</span>
                            <span className="mobile-summary-meta">
                                <span>{LocalMediaProfileTypeReg.getLabelLoose(p.type)}</span>
                                <span>{getAvailableForLabel(p)}</span>
                                <span>{PreferredFormatReg.getLabelLoose(p.preferredFormat)}</span>
                                <span>{formatBytes(p.storageSizeBytes) || '0 KiB'}</span>
                            </span>
                        </>
                    )}
                    rowHref={(p) => `/local-media-profile/${p.slug}`}
                    mobileRowActionLabel="View"
                    actions={(p) => [
                        {
                            href: `/edit-local-media-profile/${p.slug}`,
                            icon: editIcon,
                            text: 'Edit',
                            classes: 'btn',
                        },
                        {
                            href: `/add-local-media-profile?duplicate=${encodeURIComponent(p.slug)}`,
                            icon: duplicateIcon,
                            text: 'Duplicate',
                            classes: 'btn',
                        },
                        {
                            onClick: () => confirmRef.current?.open(p),
                            icon: deleteIcon,
                            text: 'Delete',
                            classes: 'btn btn-danger',
                        },
                    ]}
                />
                <LoadMore {...table} noun="profiles"/>
            </div>

            <ProfileBulkEdit
                selection={selection}
                endpoint="local-media-profiles"
                noun={['media profile', 'media profiles']}
                names={names}
                fields={BULK_FIELDS}
                deleteNote="A media profile that is still used is left as it is. Downloaded files stay where they are."
                invalidate={[['localMediaProfilesView'], ['localMediaProfiles']]}
            />

            <ConfirmDeleteDialog
                ref={confirmRef}
                title="Delete media profile"
                subjectProp="name"
                deleteRequest={(p) => {
                    const endpoint = localMediaProfileEndpoint(p.type)
                    const path = `${endpoint}/${p.slug}`
                    return fetch(`${apiUrl()}/${path}`, { method: 'DELETE', credentials: 'include' })
                }}
                invalidateQueries={[["localMediaProfiles"], ["localMediaProfilesView"]]}
                inUseMessage="This media profile is in use, it cannot be deleted"
            />
        </section>
    )
}
