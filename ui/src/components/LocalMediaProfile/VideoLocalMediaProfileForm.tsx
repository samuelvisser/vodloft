import {UseFormReturn} from 'react-hook-form'

import {DEFAULT_VIDEO_OUTPUT_TEMPLATE} from '../../types/schemas/video_local_media_profile'
import OutputTemplateEditor from './OutputTemplateEditor'

export default function VideoLocalMediaProfileForm({form}: { form: UseFormReturn<any> }) {
    return (
        <OutputTemplateEditor
            form={form}
            mode="video"
            placeholder={DEFAULT_VIDEO_OUTPUT_TEMPLATE}
            help={(
                <>
                    <p>
                        A Video profile stores what you add on its own, outside any collection: single videos, and
                        movies with their extras such as trailers. Date variables use the upload date of a video and
                        the release date of a movie. Sites do not always say when something was uploaded or who
                        made it, so those variables can be empty; a conditional can leave them out.
                    </p>
                    <p>
                        Fall back to the site's name when a video has no channel:<br/>
                        <code>{'{{ author or source }}'}</code>
                    </p>
                    <p>
                        Titles are not unique, so the filename should include <b>{'{{ slug }}'}</b>, the site's own
                        id for the item, to keep two videos with the same title apart.
                    </p>
                    <p>
                        <b>Movies and their extras.</b> Every variable beginning with <b>movie_</b> describes the parent movie, and is empty for a
                        single video. Every variable without that prefix describes the item being downloaded. For a
                        movie both describe the movie; for an extra, variables such as <b>{'{{ title }}'}</b>,
                        <b> {'{{ slug }}'}</b> and <b>{'{{ year }}'}</b> describe that extra.
                        <b> {'{{ media_type }}'}</b> is <code>movie</code>, <code>video</code> or the extra's type,
                        such as <code>trailer</code>.
                    </p>
                    <p>
                        Keep movies in a folder of their own, with the release year when it is known:<br/>
                        <code>{"{{ movie_title }}{% if movie_year %} ({{ movie_year }}){% endif %}"}</code>
                    </p>
                    <p>
                        Add an extra's type without changing movie filenames:<br/>
                        <code>{"{{ title }}{% if media_type != 'movie' %}-{{ media_type }}{% endif %}.ext"}</code>
                    </p>
                    <p>
                        Extras have no author or rating of their own, so <b>{'{{ author }}'}</b>,
                        <b> {'{{ mature_rating }}'}</b> and <b>{'{{ rating }}'}</b> are empty for them. Their
                        <b> movie_</b> equivalents still describe the parent movie.
                    </p>
                </>
            )}
        />
    )
}
