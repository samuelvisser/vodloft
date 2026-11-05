import {useMemo} from 'react'
import {UseFormReturn, useWatch} from 'react-hook-form'

import {useSources} from '../../lib/queries'
import {MoviePreferredFormatReg, offersFormat, profileDownloadOptions} from '../../types/local_media_profile'
import LocalMediaProfilePreferredFormatField from './LocalMediaProfilePreferredFormatField'
import OutputTemplateEditor from './OutputTemplateEditor'

export default function MovieLocalMediaProfileForm({form}: { form: UseFormReturn<any> }) {
    const {data: sources} = useSources()
    const sourceKeys = useWatch({control: form.control, name: 'sourceKeys'}) as string[] | null
    // Only the resolutions the Sites of the profile's Sources have.
    const formats = useMemo(() => {
        const offered = profileDownloadOptions(sources, 'movie', sourceKeys)
        return {options: MoviePreferredFormatReg.options.filter((option) => !offered || offersFormat(offered, option.value))}
    }, [sources, sourceKeys])
    return (
        <>
            <hr className="form-section-divider" aria-hidden="true"/>
            <LocalMediaProfilePreferredFormatField form={form} formatRegistry={formats}/>
            <OutputTemplateEditor
                form={form}
                mode="movie"
                placeholder={'/downloads/movies/{{ movie_title }}{% if movie_year %} ({{ movie_year }}){% endif %}/{{ title }}.ext'}
                help={(
                    <>
                        <p>
                            Every variable beginning with <b>movie_</b> describes the parent movie. Every variable without
                            that prefix describes the item being downloaded. For a movie download both contexts describe
                            the movie; for an extra download variables such as <b> {'{{ title }}'}</b>,
                            <b> {'{{ slug }}'}</b>, and <b> {'{{ year }}'}</b> describe that extra.
                        </p>
                        <p>
                            Add the parent movie's release year when known:<br/>
                            <code>{"{{ movie_title }}{% if movie_year %} ({{ movie_year }}){% endif %}"}</code>
                        </p>
                        <p>
                            Add an extra type without changing movie filenames:<br/>
                            <code>{"{{ title }}{% if media_type != 'movie' %}-{{ media_type }}{% endif %}.ext"}</code>
                        </p>
                        <p>
                            Unprefixed date variables use the current item's date: the release date for a movie or the
                            publication timestamp for an extra. The <b>movie_</b> date variables always use the parent
                            movie's release date. Dates VODLoft does not know are empty, so a conditional can omit them.
                        </p>
                        <p>
                            Sources do not currently provide separate author or rating metadata for movie extras, so
                            unprefixed <b>{'{{ author }}'}</b>, <b>{'{{ mature_rating }}'}</b>, and
                            <b> {'{{ rating }}'}</b> are empty for those items. Their <b>movie_</b> equivalents remain
                            available from the parent movie.
                        </p>
                        <p>
                            The filename should reference an item-specific variable such as <b>{'{{ title }}'}</b> or
                            <b> {'{{ media_type }}'}</b> so an extra cannot overwrite its movie.
                        </p>
                    </>
                )}
            />
        </>
    )
}
