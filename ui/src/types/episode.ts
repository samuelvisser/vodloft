export enum EpisodePublishStatus {
    scheduled = 'Scheduled',
    delayed = 'Delayed',
    live = 'Live',
    noUsableMedia = 'No usable media',
    dwProcessing = 'Processing at the source',
    publishedWithCountdown = 'Published (with countdown)',
    publishedFinal = 'Published',
}

/** Wire values (snake_case, as sent by the backend) of an episode's publishStatus. */
export const PUBLISH_STATUS_LABELS: Record<string, string> = {
    scheduled: 'Scheduled',
    delayed: 'Officially delayed',
    live: 'Live',
    no_usable_media: 'No usable media',
    dw_processing: 'Processing at the source',
    published_with_countdown: 'Published (still contains countdown)',
    published_final: 'Published',
}