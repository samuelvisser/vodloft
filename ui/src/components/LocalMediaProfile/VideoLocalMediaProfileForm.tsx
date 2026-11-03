import {UseFormReturn} from 'react-hook-form'

import {DEFAULT_VIDEO_OUTPUT_TEMPLATE} from '../../types/schemas/video_local_media_profile'
import QualityField from './QualityField'
import OutputTemplateEditor from './OutputTemplateEditor'

export default function VideoLocalMediaProfileForm({form}: { form: UseFormReturn<any> }) {
    return (
        <>
            <hr className="form-section-divider" aria-hidden="true"/>
            <QualityField form={form}/>
            <OutputTemplateEditor
                form={form}
                mode="video"
                placeholder={DEFAULT_VIDEO_OUTPUT_TEMPLATE}
                help={(
                    <>
                        <p>
                            A Video profile stores single videos that you added on their own, outside any collection.
                            Date variables use the upload date. Sites do not always say when a video was uploaded or
                            who uploaded it, so those variables can be empty; a conditional can leave them out.
                        </p>
                        <p>
                            Fall back to the site's name when a video has no channel:<br/>
                            <code>{'{{ author or source }}'}</code>
                        </p>
                        <p>
                            Titles are not unique, so the filename should include <b>{'{{ slug }}'}</b>, the site's own
                            id for the video, to keep two videos with the same title apart.
                        </p>
                    </>
                )}
            />
        </>
    )
}
