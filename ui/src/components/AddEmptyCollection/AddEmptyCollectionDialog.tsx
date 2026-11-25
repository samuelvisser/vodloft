import {zodResolver} from '@hookform/resolvers/zod'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useQueryClient} from '@tanstack/react-query'
import {Controller, useForm} from 'react-hook-form'
import {useNavigate} from 'react-router-dom'
import {z} from 'zod'

import {faIcon} from '../../icons/faIcon'
import {apiUrl} from '../../lib/api'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {getZodDefaults} from '../../utils/defaultZod'
import {createSelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../common/SimpleSelect'
import Modal from '../Modal/Modal'
import './AddEmptyCollectionDialog.css'

/** The types of custom collection, which starts empty and is filled with links. */
const EmptyCollectionTypeReg = createSelectRegistry('EmptyCollectionType', {
    series: {label: 'Series', help: 'Videos, with a list for each link you add'},
    music: {label: 'Music', help: 'Tracks, with an album for each link you add'},
})

const EmptyCollectionSchema = z.object({
    title: z.string().trim().min(1, 'Give the collection a name').max(200, 'Keep the name under 200 characters').default(''),
    type: z.enum(EmptyCollectionTypeReg.values).default('series'),
})
type EmptyCollectionValues = z.input<typeof EmptyCollectionSchema>
type CreatedCollection = {slug: string}

type Props = {
    onDismiss: () => void
}

/** Start a custom collection: it has no link of its own, and holds only what the links the user adds to it have. */
export default function AddEmptyCollectionDialog({onDismiss}: Props) {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const form = useForm<EmptyCollectionValues>({
        resolver: zodResolver(EmptyCollectionSchema),
        defaultValues: getZodDefaults(EmptyCollectionSchema),
    })
    const {register, control, formState: {errors, isSubmitting}} = form
    const onSubmit = buildServerAwareSubmit<EmptyCollectionValues, EmptyCollectionValues, CreatedCollection>(
        form,
        async (data) => fetch(`${apiUrl()}/collections/links-only`, {
            method: 'POST',
            credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: (data.title ?? '').trim(), type: data.type}),
        }),
        {
            parseSuccess: async (response) => (await response.json()) as CreatedCollection,
            onSuccess: async (created) => {
                await Promise.all([
                    queryClient.invalidateQueries({queryKey: ['collections']}),
                    queryClient.invalidateQueries({queryKey: ['collectionsView']}),
                ])
                navigate(`/edit-collection/${encodeURIComponent(created.slug)}?seasons=1`)
            },
            fallbackField: 'title',
        },
    )

    return (
        <Modal onDismiss={onDismiss} dismissOnEscape={!isSubmitting} dismissOnOverlayClick={false}
               labelledBy="empty-collection-title" onSubmit={onSubmit}>
            <div className="modal-header">
                <div className="modal-icon" aria-hidden><FontAwesomeIcon icon={faIcon('fass', 'folder-plus')}/></div>
                <h2 id="empty-collection-title" className="modal-title">Add custom collection</h2>
            </div>
            <p className="modal-text">
                The collection starts without videos. Next, add the playlists, channels or videos it should hold,
                from any site.
            </p>
            <div className="empty-collection-fields">
                <div className="form-row">
                    <label htmlFor="empty-collection-name">Name</label>
                    <input id="empty-collection-name" className="input" type="text" autoFocus
                           aria-invalid={Boolean(errors.title)} {...register('title')}/>
                    {errors.title && <div className="error" role="alert">{String(errors.title.message)}</div>}
                </div>
                <div className="form-row">
                    <label htmlFor="empty-collection-type">Type</label>
                    <Controller control={control} name="type" render={({field}) => (
                        <SimpleSelect inputId="empty-collection-type" registry={EmptyCollectionTypeReg}
                                      value={field.value} onChange={field.onChange}/>
                    )}/>
                    {errors.type && <div className="error" role="alert">{String(errors.type.message)}</div>}
                </div>
            </div>
            <div className="modal-actions">
                <button type="button" className="btn" onClick={onDismiss} disabled={isSubmitting}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
                    {isSubmitting ? 'Adding…' : 'Add and choose links'}
                </button>
            </div>
        </Modal>
    )
}
