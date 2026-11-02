import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {useExistingFilesScans} from './api'

type Props = {
    collectionSlug: string
    profileName: (localMediaProfileId: number) => string
    onOpen: (localMediaProfileId: number) => void
}

/** Shows each open scan of existing files, so a held Download Profile isn't forgotten. */
export default function ExistingFilesBanner({collectionSlug, profileName, onOpen}: Props) {
    const {data: scans} = useExistingFilesScans(collectionSlug, true)
    const open = (scans ?? []).filter((scan) => scan.status !== 'finished')
    if (open.length === 0) return null
    return (
        <>
            {open.map((scan) => {
                const found = scan.counts.certain + scan.counts.likely + scan.counts.review
                const text = scan.status === 'waiting' ? 'Waiting for the episodes to be indexed, then VODLoft looks for existing files.'
                    : scan.status === 'scanning' ? 'Looking for existing files…'
                    : scan.status === 'failed' ? 'The scan for existing files failed.'
                    : `${found} existing file${found === 1 ? '' : 's'} found, ${scan.counts.adopted} adopted.`
                return (
                    <div key={scan.localMediaProfileId} className="form-info-card existing-files-banner" role="status">
                        <span>
                            <FontAwesomeIcon icon={faIcon('fass', 'file-import')} aria-hidden="true"/>{' '}
                            <strong>{profileName(scan.localMediaProfileId)}:</strong> {text}
                            {scan.heldDownloadProfiles > 0 && ' Downloads wait until you are done.'}
                        </span>
                        <button type="button" className="btn" onClick={() => onOpen(scan.localMediaProfileId)}>
                            {scan.status === 'ready' ? 'Review' : 'Open'}
                        </button>
                    </div>
                )
            })}
        </>
    )
}
