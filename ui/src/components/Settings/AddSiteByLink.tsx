import {useQueryClient} from '@tanstack/react-query'
import {useForm} from 'react-hook-form'
import {z} from 'zod'
import {zodResolver} from '@hookform/resolvers/zod'

import {apiUrl} from '../../lib/api'
import {SiteAddedReadSchema, type SiteAddedRead} from '../../types/schemas/source'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import './SiteSettingsCard.css'

const AddSiteSchema = z.object({
    url: z.string().trim().min(1, 'Paste a link to a channel or video on the site').url('Paste a whole link, starting with https://'),
})
type AddSiteValues = z.input<typeof AddSiteSchema>

/** Add a Site by a link to it, before VODLoft has anything from it, so it gets its own settings and sign-in.
 *  Every list of Sites shows it once it is added. */
export default function AddSiteByLink() {
    const queryClient = useQueryClient()
    const form = useForm<AddSiteValues>({
        resolver: zodResolver(AddSiteSchema),
        defaultValues: {url: ''},
    })
    const {register, formState: {errors, isSubmitting}} = form
    const onSubmit = buildServerAwareSubmit<AddSiteValues, AddSiteValues, SiteAddedRead>(
        form,
        async (data) => fetch(`${apiUrl()}/sources/sites`, {
            method: 'POST',
            credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: data.url.trim()}),
        }),
        {
            parseSuccess: async (response) => SiteAddedReadSchema.parse(await response.json()),
            onSuccess: async (_site, {resetForm}) => {
                resetForm({url: ''})
                await Promise.all([
                    queryClient.invalidateQueries({queryKey: ['siteSignIns']}),
                    queryClient.invalidateQueries({queryKey: ['sitesSettings']}),
                ])
            },
            fallbackField: 'url',
        },
    )
    return (
        <form className="site-add" onSubmit={onSubmit} noValidate>
            <div className="site-add__line">
                <input
                    className="input settings-input" type="url" placeholder="Add a site: https://www.twitch.tv/…"
                    aria-label="Link to a channel or video on the site to add" aria-invalid={Boolean(errors.url)}
                    {...register('url')}
                />
                <button className="btn" type="submit" disabled={isSubmitting}>Add site</button>
            </div>
            {errors.url
                ? <div className="error" role="alert">{String(errors.url.message)}</div>
                : <div className="site-add__help">A site shows up once you add something from it. Paste a link to a channel or video to add it now.</div>}
        </form>
    )
}
