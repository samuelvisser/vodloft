import {useQueryClient} from '@tanstack/react-query'
import {useForm} from 'react-hook-form'
import {z} from 'zod'
import {zodResolver} from '@hookform/resolvers/zod'

import {apiUrl} from '../../lib/api'
import {SiteAddedReadSchema, type SiteAddedRead} from '../../types/schemas/source'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import './SiteSettingsCard.css'

const SITE_ADDRESS_MESSAGE = "Type the site's address, such as twitch.tv, or paste a link to a page on it"

/** Whether a link names a site on the internet: its host has a domain, such as twitch.tv. */
const onAnInternetSite = (url: string) => {
    try {
        return new URL(url).hostname.includes('.')
    } catch {
        return false
    }
}

const AddSiteSchema = z.object({
    url: z.string().trim().min(1, SITE_ADDRESS_MESSAGE)
        // An address typed without https://, such as twitch.tv, is the site's https address.
        .transform((url) => url.includes('://') ? url : `https://${url}`)
        .pipe(z.url(SITE_ADDRESS_MESSAGE).refine(onAnInternetSite, SITE_ADDRESS_MESSAGE)),
})
type AddSiteValues = z.input<typeof AddSiteSchema>
type AddSiteData = z.output<typeof AddSiteSchema>

/** Add a Site by a link to it, before VODLoft has anything from it, so it gets its own settings and authentication.
 *  Every list of Sites shows it once it is added. */
export default function AddSiteByLink({onAdded, help}: {
    /** Called with the Site once it is added. */
    onAdded?: (site: SiteAddedRead) => void
    /** What the field says below it, in place of the usual help. */
    help?: string
} = {}) {
    const queryClient = useQueryClient()
    const form = useForm<AddSiteValues>({
        resolver: zodResolver(AddSiteSchema),
        defaultValues: {url: ''},
    })
    const {register, formState: {errors, isSubmitting}} = form
    const onSubmit = buildServerAwareSubmit<AddSiteValues, AddSiteData, SiteAddedRead>(
        form,
        async (data) => fetch(`${apiUrl()}/sources/sites`, {
            method: 'POST',
            credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: data.url}),
        }),
        {
            parseSuccess: async (response) => SiteAddedReadSchema.parse(await response.json()),
            onSuccess: async (site, {resetForm}) => {
                resetForm({url: ''})
                onAdded?.(site)
                await Promise.all([
                    queryClient.invalidateQueries({queryKey: ['siteAuthentication']}),
                    queryClient.invalidateQueries({queryKey: ['sitesSettings']}),
                    queryClient.invalidateQueries({queryKey: ['sourceSites']}),
                    queryClient.invalidateQueries({queryKey: ['localMediaProfileSites']}),
                    queryClient.invalidateQueries({queryKey: ['localMediaProfilesView']}),
                    queryClient.invalidateQueries({queryKey: ['siteChoices']}),
                    // Add Media only offers the search of a Site that is added.
                    queryClient.invalidateQueries({queryKey: ['sources']}),
                ])
            },
            fallbackField: 'url',
        },
    )
    return (
        <form className="site-add" onSubmit={onSubmit} noValidate>
            <div className="site-add__line">
                <input
                    className="input settings-input" type="url" placeholder="Add a site: twitch.tv"
                    aria-label="Address of the site to add, or a link to a page on it" aria-invalid={Boolean(errors.url)}
                    {...register('url')}
                />
                <button className="btn" type="submit" disabled={isSubmitting}>Add site</button>
            </div>
            {errors.url
                ? <div className="error" role="alert">{String(errors.url.message)}</div>
                : <div className="site-add__help">{help ?? 'A site shows up once you add something from it. Type its address, such as twitch.tv, or paste a link to a page on it to add it now.'}</div>}
        </form>
    )
}
