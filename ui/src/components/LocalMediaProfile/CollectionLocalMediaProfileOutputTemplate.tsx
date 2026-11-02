import {UseFormReturn} from 'react-hook-form'

import OutputTemplateEditor from './OutputTemplateEditor'
import CollectionAssetsField from './CollectionAssetsField'

export default function CollectionLocalMediaProfileOutputTemplate({form}: { form: UseFormReturn<any> }) {
    return (
        <OutputTemplateEditor
            form={form}
            mode="collection"
            placeholder={'/downloads/shows/{{ collection }}/{{ episode_title }}.ext'}
            renderPreviewFields={(preview) => <CollectionAssetsField form={form} preview={preview}/>}
            help={(
                <>
                    <p>
                        Collection, season, episode, and publication-date values are available. The editor's variable menu
                        lists every supported value and explains what it represents.
                    </p>
                    <p>
                        Conditional year example:<br/>
                        <code>{"{{ episode_title }}{% if year %} ({{ year }}){% endif %}.ext"}</code>
                    </p>
                    <p>
                        If a date, season, or another optional value is not known, it is an empty string. Use an
                        <b> if</b> block to omit any punctuation or folders that belong with it.
                    </p>
                </>
            )}
        />
    )
}
