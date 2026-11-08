import {useCallback, useRef} from 'react'
import {can} from '../lib/access'
import {Link} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import {useDownloadProfilesTable} from '../lib/queries'
import {updateLazyCollectionEntities} from '../lib/lazyCollection'
import LoadMore from '../components/common/LoadMore'
import {DownloadProfileReadView} from '../types/schemas/download_profile_view'
import {PreferredFormatReg} from '../types/local_media_profile'
import DataTable, {Column} from '../components/DataTable/DataTable'
import ConfirmDeleteDialog, {ConfirmDeleteDialogRef} from '../components/ConfirmDeleteDialog/ConfirmDeleteDialog'
import PageSubtitle from "../components/common/PageSubtitle";
import ProfileEnabledSwitch from '../components/common/ProfileEnabledSwitch'
import {DownloadProfileUpdateSchema} from '../types/schemas/download_profile'
import {faIcon} from '../icons/faIcon'
import {formatBytes} from '../utils/formatting'
import {apiUrl} from '../lib/api'

export default function DownloadProfilesPage() {
    const queryClient = useQueryClient()

    const table = useDownloadProfilesTable()

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
            <div className="view-header">
                <h1 id="profiles-title">Download Profiles</h1>
                <PageSubtitle summary={<>Create rules for how each collection is downloaded.</>}>
                    <p>A Download Profile tells VODLoft what to download and how long to retain your downloads.
                        Each collection can contain multiple download profiles, allowing you to
                        download both audio and video versions of episodes for example.</p>
                    <p>Download Profiles are always connected to a Local Media Profile, which defines where your
                        downloads will be stored and what their file name should be.</p>
                </PageSubtitle>
                {can('download_profiles', 'manage') && <Link className="btn btn-primary" to="/add-download-profile">Add download profile</Link>}
            </div>

            <div className="form-row">
                <DataTable<DownloadProfileReadView>
                    ariaLabel="Existing download profiles"
                    columns={columns}
                    data={table.isLoading ? undefined : table.items}
                    loading={table.isLoading}
                    error={table.error}
                    rowKey={(p) => String(p.id)}
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
