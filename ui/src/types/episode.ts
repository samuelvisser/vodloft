export enum EpisodePublishStatus {
    scheduled = 'Scheduled',
    delayed = 'Delayed',
    live = 'Live',
    noUsableMedia = 'No usable media',
    sourceProcessing = 'Processing at the source',
    publishedPreliminary = 'Preliminary version',
    publishedFinal = 'Published',
}

/**
 * Neutral names for the wire values (snake_case, as sent by the backend) of an episode's publishStatus,
 * for places that do not know the episode's Source. Where the Source is known, use its own names
 * from usePublishStatusLabels.
 */
export const PUBLISH_STATUS_LABELS: Record<string, string> = {
    scheduled: 'Upcoming',
    delayed: 'Delayed',
    live: 'Live',
    no_usable_media: 'No usable media',
    source_processing: 'Processing at the source',
    published_preliminary: 'Preliminary version',
    published_final: 'Published',
}