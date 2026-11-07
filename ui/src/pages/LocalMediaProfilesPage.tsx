import {useRef, useState} from 'react'
import ProfileTableFilters, {ChipFilter, FORMAT_KIND_OPTIONS, formatKind, matchesChips, matchesWords, searchWords} from '../components/common/ProfileTableFilters'
import {can} from '../lib/access'
import {Link} from 'react-router-dom'
import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {useLocalMediaProfilesView} from '../lib/queries'
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
import PageSubtitle from "../components/common/PageSubtitle";
import OpaqueOutputTemplateCode from '../components/LocalMediaProfile/OpaqueOutputTemplateCode'
import {localMediaProfileEndpoint} from '../types/local_media_profile'
import './LocalMediaProfilesPage.css'
import {apiUrl} from '../lib/api'

type LocalMediaProfileOverviewRow = LocalMediaProfileRead & {
    storageSizeBytes: number
}

function getAvailableForLabel(profile: LocalMediaProfileRead) {
    return profile.type === 'collection'
        ? CollectionLocalMediaProfileScopeReg.getLabelLoose(profile.collectionScope)
        : 'Movies'
}

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

function usedFor(profile: LocalMediaProfileRead): string[] {
    if (profile.type !== 'collection') return [profile.type]
    return profile.collectionScope === 'both' ? ['podcast', 'series'] : [profile.collectionScope]
}

export default function LocalMediaProfilesPage() {
    const editIcon: IconProp = faIcon('fass', 'pen-to-square')
    const deleteIcon: IconProp = faIcon('fass', 'trash')

    const confirmRef = useRef<ConfirmDeleteDialogRef>(null)

    const columns: Column<LocalMediaProfileOverviewRow>[] = [
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

    const {data: profileViews, isLoading, error} = useLocalMediaProfilesView()
    const profiles = profileViews?.map(
        ({profile, statistics}): LocalMediaProfileOverviewRow => ({
            ...profile,
            storageSizeBytes: statistics.storageSizeBytes,
        }),
    ).sort((left, right) => left.name.localeCompare(right.name, undefined, {sensitivity: 'base', numeric: true}))

    const [search, setSearch] = useState('')
    const [usedForFilter, setUsedForFilter] = useState<Set<string>>(new Set())
    const [formatFilter, setFormatFilter] = useState<Set<string>>(new Set())
    const [storageFilter, setStorageFilter] = useState<Set<string>>(new Set())
    const words = searchWords(search)
    const shownProfiles = profiles?.filter((p) => (
        matchesWords(words, p.name, p.outputTemplate)
        && (usedForFilter.size === 0 || usedFor(p).some((value) => usedForFilter.has(value)))
        && matchesChips(formatKind(p.preferredFormat), formatFilter)
        && matchesChips(p.storageSizeBytes > 0 ? 'files' : 'empty', storageFilter)
    ))
    const filtered = words.length > 0 || usedForFilter.size > 0 || formatFilter.size > 0 || storageFilter.size > 0

    return (
        <section className="view" aria-labelledby="profiles-title">
            <div className="view-header">
                <h1 id="profiles-title">Local Media Profiles</h1>
                <PageSubtitle summary={<>Define how downloaded files are stored and in what format.</>}>
                    <p>A Local Media Profile controls the output path and the preferred file format for your downloads
                        across collections and movies. You can create multiple profiles (e.g., “Podcasts to ABS”, “Videos to NAS”) and
                        reuse them.</p>
                </PageSubtitle>
                {can('local_media_profiles', 'manage') && <Link className="btn btn-primary" to="/add-local-media-profile">Add media profile</Link>}
            </div>

            <ProfileTableFilters
                search={search}
                onSearch={setSearch}
                searchPlaceholder="Search names or output paths"
                shown={shownProfiles?.length ?? 0}
                total={profiles?.length ?? 0}
                noun={['profile', 'profiles']}
                filtered={filtered}
                activeCount={[usedForFilter, formatFilter, storageFilter].filter((f) => f.size > 0).length}
                onReset={() => { setSearch(''); setUsedForFilter(new Set()); setFormatFilter(new Set()); setStorageFilter(new Set()) }}
            >
                <ChipFilter label="Used for" options={USED_FOR_OPTIONS} selected={usedForFilter} onChange={setUsedForFilter}/>
                <ChipFilter label="Format" options={FORMAT_KIND_OPTIONS} selected={formatFilter} onChange={setFormatFilter}/>
                <ChipFilter label="Storage" options={STORAGE_OPTIONS} selected={storageFilter} onChange={setStorageFilter}/>
            </ProfileTableFilters>

            <div className="form-row">
                <DataTable<LocalMediaProfileOverviewRow>
                    ariaLabel="Existing media profiles"
                    columns={columns}
                    data={shownProfiles}
                    loading={isLoading}
                    error={error}
                    rowKey={(p) => p.id}
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
                            onClick: () => confirmRef.current?.open(p),
                            icon: deleteIcon,
                            text: 'Delete',
                            classes: 'btn btn-danger',
                        },
                    ]}
                />
            </div>

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
