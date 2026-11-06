import {useRef} from 'react'
import {Link} from 'react-router-dom'
import {useCollections} from '../lib/queries'
import {CollectionRead} from '../types/schemas/collection'
import DataTable, {Column} from '../components/DataTable/DataTable'
import ConfirmDeleteDialog, {ConfirmDeleteDialogRef} from '../components/ConfirmDeleteDialog/ConfirmDeleteDialog'
import {EpisodeIdentifierReg, CollectionTypeReg} from "../types/collection";
import {faIcon} from '../icons/faIcon'
import {apiUrl} from '../lib/api'

export default function CollectionsPage() {

    const {data: collections, isLoading, error} = useCollections()

    const confirmRef = useRef<ConfirmDeleteDialogRef>(null)

    const columns: Column<CollectionRead>[] = [
        {
            header: 'Title',
            accessor: (s) => s.title,
            mobileHidden: true,
        },
        {
            header: 'Author',
            accessor: (s) => s.authorName,
        },
        {
            header: 'Type',
            accessor: (s) => CollectionTypeReg.getLabelLoose(s.type),
            align: 'center',
        },
        {
            header: 'Episode ID',
            accessor: (s) => EpisodeIdentifierReg.getLabelLoose(s.episodeIdentifier),
            align: 'center',
        },
    ]

    return (
        <section className="view" aria-labelledby="collections-title">
            <div className="view-header">
                <h1 id="collections-title">Collections</h1>
                <Link className="btn btn-primary" to="/add-collection">Add collection</Link>
            </div>

            <div className="form-row">
                <DataTable<CollectionRead>
                    ariaLabel="Existing collections"
                    columns={columns}
                    data={collections}
                    loading={isLoading}
                    error={error}
                    rowKey={(s) => s.slug}
                    rowAriaLabel={(s) => s.title}
                    mobileSummary={(s) => (
                        <>
                            <span className="mobile-summary-title">{s.title}</span>
                            <span className="mobile-summary-subtitle">{s.authorName}</span>
                            <span className="mobile-summary-meta">
                                <span>{CollectionTypeReg.getLabelLoose(s.type)}</span>
                                <span aria-hidden="true">•</span>
                                <span>{EpisodeIdentifierReg.getLabelLoose(s.episodeIdentifier)}</span>
                            </span>
                        </>
                    )}
                    mobileRowActionLabel="Open collection"
                    rowHref={(s) => `/collection/${s.slug}`}
                    actions={(s) => [
                        {
                            href: `/edit-collection/${s.slug}`,
                            icon: faIcon('fass', 'pen-to-square'),
                            text: 'Edit',
                            classes: 'btn',
                        },
                        {
                            onClick: () => confirmRef.current?.open(s),
                            icon: faIcon('fass', 'trash'),
                            text: 'Delete',
                            classes: 'btn btn-danger',
                        },
                    ]}
                />
            </div>

            <ConfirmDeleteDialog
                ref={confirmRef}
                title="Delete collection"
                subjectProp={(s) => s.title}
                deleteRequest={(s) => fetch(`${apiUrl()}/collections/${encodeURIComponent(s.slug)}`, {method: 'DELETE', credentials: 'include'})}
                invalidateQueries={[['collections']]}
                inUseMessage="This collection is in use, it cannot be deleted"
            />
        </section>
    )
}
