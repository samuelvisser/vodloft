import {UseFormReturn} from 'react-hook-form'

import {DEFAULT_VIDEO_OUTPUT_TEMPLATE} from '../../types/schemas/video_local_media_profile'
import OutputTemplateEditor from './OutputTemplateEditor'

export default function VideoLocalMediaProfileForm({form}: { form: UseFormReturn<any> }) {
    return (
        <OutputTemplateEditor
            form={form}
            mode="video"
            placeholder={DEFAULT_VIDEO_OUTPUT_TEMPLATE}
        />
    )
}
