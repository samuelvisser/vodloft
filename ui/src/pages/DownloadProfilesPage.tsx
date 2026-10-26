import {useCallback, useRef} from 'react'
import {useNavigate} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import {useDownloadProfilesView} from '../lib/queries'
import {DownloadProfileReadView} from '../types/schemas/download_profile_view'
import {PreferredFormatReg} from '../types/local_media_profile'
import DataTable, {Column} from '../components/DataTable/DataTable'
import ConfirmDeleteDialog, {ConfirmDeleteDialogRef} from '../components/ConfirmDeleteDialog/ConfirmDeleteDialog'
import PageSubtitle from "../components/common/PageSubtitle";
import ProfileEnabledSwitch from '../components/common/ProfileEnabledSwitch'
import {EpisodeIdentifierReg} from "../types/show";
import {DownloadProfileUpdateSchema} from '../types/schemas/download_profile'
import {faIcon} from '../icons/faIcon'

export default function DownloadProfilesPage() {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const onAdd = useCallback(() => navigate('/add-download-profile'), [navigate])

    const {data: profiles, isLoading, error} = useDownloadProfilesView()

    const confirmRef = useRef<ConfirmDeleteDialogRef>(null)

    const setProfileEnabled = useCallback(async (profile: DownloadProfileReadView, enableProfile: boolean) => {
        try {
            const body = DownloadProfileUpdateSchema.parse({...profile, enableProfile})

            const response = await fetch(`${(window as any).appConfig.API_URL}/download-profiles/${profile.id}`, {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include',
                body: JSON.stringify(body),
            })
            if (!response.ok) throw new Error(`Failed to update download profile (${response.status})`)

            queryClient.setQueryData<DownloadProfileReadView[]>(['downloadProfilesView'], (current) => (
                current?.map((item) => (
                    item.id === profile.id
                        ? {...item, enableProfile}
                        : item
                ))
            ))

            await Promise.allSettled([
                queryClient.invalidateQueries({queryKey: ['downloadProfilesView']}),
                queryClient.invalidateQueries({queryKey: ['downloadProfilesByShowSlug']}),
            ])
        } catch (updateError) {
            toast.error(`Failed to ${enableProfile ? 'enable' : 'disable'} download profile`)
            throw updateError
        }
    }, [queryClient])

    const columns: Column<DownloadProfileReadView>[] = [
        {
            header: 'Show Title',
            accessor: (p) => p.showTitle,
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
            header: 'Episode identification',
            accessor: (p) => EpisodeIdentifierReg.getLabelLoose(p.showEpisodeIdentifier),
        },
        {
            header: 'Enabled',
            cell: (p) => (
                <ProfileEnabledSwitch
                    checked={p.enableProfile}
                    ariaLabel={`Automatic downloads for ${p.showTitle}`}
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
                <PageSubtitle summary={<>Create rules for how each show is downloaded.</>}>
                    <p>A Download Profile tells VODLoft what to download and how long to retain your downloads.
                        Each show can contain multiple download profiles, allowing you to
                        download both audio and video versions of episodes for example.</p>
                    <p>Download Profiles are always connected to a Local Media Profile, which defines where your
                        downloads will be stored and what their file name should be.</p>
                </PageSubtitle>
                <button className="btn btn-primary" onClick={onAdd}>Add download profile</button>
            </div>

            <div className="form-row">
                <DataTable<DownloadProfileReadView>
                    ariaLabel="Existing download profiles"
                    columns={columns}
                    data={profiles}
                    loading={isLoading}
                    error={error}
                    rowKey={(p) => String(p.id)}
                    rowAriaLabel={(p) => p.showTitle}
                    mobileSummary={(p) => (
                        <>
                            <span className="mobile-summary-title">{p.showTitle}</span>
                            <span className="mobile-summary-meta">
                                <span>{p.localMediaProfileName}</span>
                                <span aria-hidden="true">•</span>
                                <span>{PreferredFormatReg.getLabelLoose(p.localMediaProfilePreferredFormat)}</span>
                                <span aria-hidden="true">•</span>
                                <span>{EpisodeIdentifierReg.getLabelLoose(p.showEpisodeIdentifier)}</span>
                                <span className={`mobile-summary-status ${p.enableProfile ? 'is-success' : ''}`}>
                                    {p.enableProfile ? 'Enabled' : 'Disabled'}
                                </span>
                            </span>
                        </>
                    )}
                    onRowClick={(p) => navigate(`/edit-download-profile/${p.id}`, {state: p})}
                    actions={(p) => [
                        {
                            onClick: () => navigate(`/edit-download-profile/${p.id}`, {state: p}),
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
                title="Delete download profile"
                subjectProp="showTitle"
                deleteRequest={(p) => fetch(
                    `${(window as any).appConfig.API_URL}/download-profiles/${p.id}`,
                    {method: 'DELETE', credentials: 'include'},
                )}
                invalidateQueries={[["downloadProfilesView"], ["downloadProfilesByShowSlug"]]}
                inUseMessage="This download profile is in use, it cannot be deleted"
            />
        </section>
    )
}
