import type {LocalMediaProfilePreviewState} from '../../lib/localMediaProfilePreview'
import ReadMore from '../../utils/ReadMore'

/** The collection root of the example: where the poster, background and tvshow.nfo are saved. */
export default function CollectionRootNote({preview}: {preview: LocalMediaProfilePreviewState}) {
    const root = preview.result?.collectionRoot
    const text = preview.error
        ? null
        : root?.path
            ? root.path
            : root?.reason
                ? root.reason
                : preview.loading
                    ? 'Resolving collection root…'
                    : 'Choose an example episode to see the collection root.'
    if (text === null) return null

    return (
        <div className="help template-collection-root">
            <ReadMore summary={<>
                Collection root: <code style={{overflowWrap: 'anywhere'}}>{text}</code>. Posters, backgrounds and tvshow.nfo go here.
            </>}>
                <p>
                    VODLoft works out the folder all of a collection's episodes share, also through conditional Jinja
                    paths. The poster, background and square artwork, and the show's NFO file, are saved there when they
                    are on under Files and metadata. Artwork you added yourself is kept.
                </p>
                <p>
                    Choose another example episode to check the root. If it is not the folder you expect, the output
                    template likely has an ambiguous path.
                </p>
            </ReadMore>
        </div>
    )
}
