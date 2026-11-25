import type {SettingsTabProps} from './SettingsTabTypes'
import CronEditor from './CronEditor'
import CollectionHealthChecks from './CollectionHealthChecks'
import SiteSettingsCard from './SiteSettingsCard'
import {
    DurationField,
    NumberField,
    SettingsDisclosure,
    SettingsSection,
    TextField,
    ToggleField,
} from './SettingsControls'
import ReadMore from "../../utils/ReadMore";
import {frontendOperationDefinitions} from '../../lib/operationDefinitions'

const PENDING_SYSTEM_FIELDS = [
    {path: 'pendingUpcomingMinutes', label: 'Look upcoming episodes up every', max: 24 * 60,
        help: 'Until 15 minutes before they start.'},
    {path: 'pendingStartingMinutes', label: 'Look starting episodes up every', max: 60,
        help: 'From 15 minutes before the start until an hour after, and when the start is not known.'},
    {path: 'pendingLiveMinutes', label: 'Look live episodes up every', max: 60,
        help: 'While live, and while the site is still finishing them.'},
] as const

export default function AutomationSettingsTab({draft, updateDraft, environmentVariableFor, errorFor}: SettingsTabProps) {

    return (
        <>
            <SettingsSection
                title="Scheduler"
                description="Global execution and retry settings for VODLoft background work."
            >
                <ToggleField
                    id="settings-scheduler-enabled"
                    label="Enable automatic background tasks"
                    checked={draft.scheduler.enabled}
                    environmentVariable={environmentVariableFor('scheduler.enabled')}
                    onChange={(checked) => updateDraft((next) => {
                        next.scheduler.enabled = checked
                    })}
                    help="Disabling this stops automatic indexing, monitoring and scheduled downloads after restart. Manual operations, recovery and required maintenance can still run."
                    wide
                />
                <NumberField
                    id="settings-scheduler-workers"
                    label="Maximum workers"
                    value={draft.scheduler.maxWorkers}
                    min={1}
                    error={errorFor('scheduler.maxWorkers')}
                    environmentVariable={environmentVariableFor('scheduler.maxWorkers')}
                    onChange={(value) => updateDraft((next) => {
                        next.scheduler.maxWorkers = value
                    })}
                    help="Upper bound for parallel background task workers."
                />
                <DurationField
                    id="settings-scheduler-stalled-timeout"
                    label="Stalled task timeout"
                    value={draft.scheduler.stalledTaskTimeoutMinutes}
                    backendUnit="minutes"
                    error={errorFor('scheduler.stalledTaskTimeoutMinutes')}
                    environmentVariable={environmentVariableFor('scheduler.stalledTaskTimeoutMinutes')}
                    onChange={(value) => updateDraft((next) => {
                        next.scheduler.stalledTaskTimeoutMinutes = value
                    })}
                    help="Cancel a task or operation when its progress percentage has not changed for this long."
                />
                <NumberField
                    id="settings-scheduler-retries"
                    label="Default retries"
                    value={draft.scheduler.defaultMaxRetries}
                    min={0}
                    error={errorFor('scheduler.defaultMaxRetries')}
                    environmentVariable={environmentVariableFor('scheduler.defaultMaxRetries')}
                    onChange={(value) => updateDraft((next) => {
                        next.scheduler.defaultMaxRetries = value
                    })}
                    help="Used when a task or schedule does not specify its own retry count."
                />
                <DurationField
                    id="settings-scheduler-backoff"
                    label="Retry backoff"
                    value={draft.scheduler.retryBackoffSeconds}
                    backendUnit="seconds"
                    step={0.5}
                    error={errorFor('scheduler.retryBackoffSeconds')}
                    environmentVariable={environmentVariableFor('scheduler.retryBackoffSeconds')}
                    onChange={(value) => updateDraft((next) => {
                        next.scheduler.retryBackoffSeconds = value
                    })}
                    help="Base pause before retrying failed background work."
                />
            </SettingsSection>

            <SettingsSection
                title="Episode discovery and monitoring"
                description="Cron schedules used to find episodes and follow their publication state."
            >
                <CronEditor
                    id="settings-find-episodes-cron"
                    label="Find new episodes"
                    runNow={{
                        definition: frontendOperationDefinitions['system.cron.find_episodes'],
                        job: 'find-episodes',
                        ledger: {definitionKey: 'fetch_new_episodes', resourceType: 'collection', includeUnscoped: true},
                    }}
                    value={draft.newEpisodeSchedule.findEpisodesCron}
                    enabled={draft.newEpisodeSchedule.findEpisodesCronEnabled}
                    error={errorFor('newEpisodeSchedule.findEpisodesCron')}
                    environmentVariable={environmentVariableFor('newEpisodeSchedule.findEpisodesCron')}
                    enabledEnvironmentVariable={environmentVariableFor('newEpisodeSchedule.findEpisodesCronEnabled')}
                    onChange={(value) => updateDraft((next) => {
                        next.newEpisodeSchedule.findEpisodesCron = value
                    })}
                    onEnabledChange={(enabled) => updateDraft((next) => {
                        next.newEpisodeSchedule.findEpisodesCronEnabled = enabled
                    })}
                    help={
                        <ReadMore summary={<span>Finds new episodes for every collection indexed in VODLoft.</span>}>
                            <p>
                                This cron schedule determines how often VODLoft will search for new episodes across all collections.
                                It is recommended to set this to a value that is not too frequent, as it can impact performance.
                            </p>
                        </ReadMore>
                    }
                />
                <CronEditor
                    id="settings-quick-check-cron"
                    label="Quick check for new videos"
                    runNow={{
                        definition: frontendOperationDefinitions['system.cron.quick_check'],
                        job: 'quick-check',
                        ledger: {definitionKey: 'quick_check_new_videos', resourceType: 'system', resourceId: 0},
                    }}
                    value={draft.newEpisodeSchedule.quickCheckCron}
                    enabled={draft.newEpisodeSchedule.quickCheckCronEnabled}
                    error={errorFor('newEpisodeSchedule.quickCheckCron')}
                    environmentVariable={environmentVariableFor('newEpisodeSchedule.quickCheckCron')}
                    enabledEnvironmentVariable={environmentVariableFor('newEpisodeSchedule.quickCheckCronEnabled')}
                    onChange={(value) => updateDraft((next) => {
                        next.newEpisodeSchedule.quickCheckCron = value
                    })}
                    onEnabledChange={(enabled) => updateDraft((next) => {
                        next.newEpisodeSchedule.quickCheckCronEnabled = enabled
                    })}
                    help={
                        <ReadMore summary={<span>Looks for new videos in YouTube channels and other yt-dlp collections.</span>}>
                            <p>
                                Each run looks only at the newest videos of the collections that are due, and adds what is new.
                                How often a collection is due depends on the YouTube API quota, and is never more often than the
                                shortest check interval under Sources. These collections are not part of <code>Find new episodes</code>.
                            </p>
                        </ReadMore>
                    }
                />
                <CronEditor
                    id="settings-full-rescan-cron"
                    label="Re-scan collections with quick checks"
                    runNow={{
                        definition: frontendOperationDefinitions['system.cron.full_rescan'],
                        job: 'full-rescan',
                        ledger: {definitionKey: 'rescan_quick_checked_collections', resourceType: 'collection', includeUnscoped: true},
                    }}
                    value={draft.newEpisodeSchedule.fullRescanCron}
                    enabled={draft.newEpisodeSchedule.fullRescanCronEnabled}
                    error={errorFor('newEpisodeSchedule.fullRescanCron')}
                    environmentVariable={environmentVariableFor('newEpisodeSchedule.fullRescanCron')}
                    enabledEnvironmentVariable={environmentVariableFor('newEpisodeSchedule.fullRescanCronEnabled')}
                    onChange={(value) => updateDraft((next) => {
                        next.newEpisodeSchedule.fullRescanCron = value
                    })}
                    onEnabledChange={(enabled) => updateDraft((next) => {
                        next.newEpisodeSchedule.fullRescanCronEnabled = enabled
                    })}
                    help={
                        <ReadMore summary={<span>Lists the collections with quick checks in full, once a day by default.</span>}>
                            <p>
                                Catches anything a quick check missed, such as an older video made public later. With a
                                YouTube API key this costs about 1 unit per 50 videos of each collection.
                            </p>
                        </ReadMore>
                    }
                />
            </SettingsSection>

            <SettingsSection
                title="Collection health"
                description="Makes sure every collection is healthy, so Home and the Library show what needs you. The checks below are saved as soon as you change them."
            >
                <CronEditor
                    id="settings-collection-health-cron"
                    label="Check collection health"
                    runNow={{
                        definition: frontendOperationDefinitions['system.cron.collection_health'],
                        job: 'collection-health',
                        ledger: {definitionKey: 'check_collection_health', resourceType: 'system', resourceId: 0},
                    }}
                    value={draft.collectionHealth.checkCron}
                    enabled={draft.collectionHealth.checkCronEnabled}
                    error={errorFor('collectionHealth.checkCron')}
                    environmentVariable={environmentVariableFor('collectionHealth.checkCron')}
                    enabledEnvironmentVariable={environmentVariableFor('collectionHealth.checkCronEnabled')}
                    onChange={(value) => updateDraft((next) => {
                        next.collectionHealth.checkCron = value
                    })}
                    onEnabledChange={(enabled) => updateDraft((next) => {
                        next.collectionHealth.checkCronEnabled = enabled
                    })}
                    help={
                        <ReadMore summary={<span>Checks every collection once a night by default, and sets right what drifted.</span>}>
                            <p>
                                VODLoft keeps track of what each collection needs from you as it works, such as downloads that
                                wait to be moved to another season. This check works it out again for every collection, in
                                case something was missed, and marks the collections that need you.
                            </p>
                        </ReadMore>
                    }
                />
                <CollectionHealthChecks/>
            </SettingsSection>

            <SettingsSection
                title="Per-Site scheduling"
                description="How each Site's new uploads are looked up again, and how its upcoming and live videos are followed."
            >
                <div className="settings-field settings-field--wide site-settings-system">
                    <label>System settings</label>
                    <div className="settings-field__help">Used by every Site that follows the system setting, and by Sites VODLoft has not seen yet.</div>
                </div>
                <TextField
                    id="settings-metadata-refresh-intervals"
                    label="Metadata refresh"
                    value={draft.newEpisodeSchedule.metadataRefreshIntervals}
                    error={errorFor('newEpisodeSchedule.metadataRefreshIntervals')}
                    environmentVariable={environmentVariableFor('newEpisodeSchedule.metadataRefreshIntervals')}
                    onChange={(value) => updateDraft((next) => {
                        next.newEpisodeSchedule.metadataRefreshIntervals = value
                    })}
                    help={
                        <ReadMore summary={<span>When VODLoft looks new uploads up again.</span>}>
                            <p>
                                Creators often change a title, description or thumbnail after publishing. VODLoft looks each
                                new episode and video up again at these offsets after publication, and after the last one its
                                metadata is final. Only what VODLoft shows and serves in its feeds changes: downloaded files keep their
                                names and metadata.
                            </p>
                            <p>
                                Value is a list of comma-separated offsets after publication. Use s, m, h or d, for example: 120s,30m,3h,2d
                            </p>
                        </ReadMore>
                    }
                />
                <ToggleField
                    id="settings-upcoming-and-live"
                    label="Upcoming and live videos"
                    checked={draft.newEpisodeSchedule.upcomingAndLive}
                    environmentVariable={environmentVariableFor('newEpisodeSchedule.upcomingAndLive')}
                    onChange={(checked) => updateDraft((next) => {
                        next.newEpisodeSchedule.upcomingAndLive = checked
                    })}
                    help={
                        <ReadMore summary={<span>Follow streams and premieres from when they are announced.</span>}>
                            <p>
                                VODLoft adds a stream or premiere as soon as it is announced and follows it until it is
                                published, then downloads it. It never records a stream while it is live. Turned off, upcoming
                                episodes only change when their collection is scanned again.
                            </p>
                        </ReadMore>
                    }
                />
                {PENDING_SYSTEM_FIELDS.map(({path, label, max, help}) => (
                    <NumberField
                        key={path}
                        id={`settings-${path}`}
                        label={label}
                        unit="min"
                        min={2}
                        max={max}
                        value={draft.newEpisodeSchedule[path]}
                        error={errorFor(`newEpisodeSchedule.${path}`)}
                        environmentVariable={environmentVariableFor(`newEpisodeSchedule.${path}`)}
                        onChange={(value) => updateDraft((next) => {
                            next.newEpisodeSchedule[path] = value
                        })}
                        help={help}
                    />
                ))}
                <SiteSettingsCard
                    groups={['scheduling']} draft={draft} updateDraft={updateDraft} errorFor={errorFor}
                    help="Default follows the system settings above. A Site with a preset starts with its own value, which you can change or set back to Default."
                />
            </SettingsSection>

            <SettingsDisclosure
                title="Episode lifecycle timing"
                description="Fallback and cleanup thresholds used while an episode's state at its source is settling."
            >
                <DurationField
                    id="settings-published-final"
                    label="Final publication threshold"
                    value={draft.episodeStatusTiming.publishedFinalAfterMinutes}
                    backendUnit="minutes"
                    error={errorFor('episodeStatusTiming.publishedFinalAfterMinutes')}
                    environmentVariable={environmentVariableFor('episodeStatusTiming.publishedFinalAfterMinutes')}
                    onChange={(value) => updateDraft((next) => {
                        next.episodeStatusTiming.publishedFinalAfterMinutes = value
                    })}
                    help={
                        <ReadMore summary={<span>Set to published final if still at published with countdown after this duration.</span>}>
                            <p>
                                Usually, VODLoft can determine an episode's status accurately. However, sometimes it might get stuck in <code>published
                                with countdown</code>.
                                If your download profiles are setup to only download <code>published final</code> episodes, this means they still skip
                                it. This setting acts
                                as a safety net to ensure <code>published with countdown</code> episodes eventually will always be considered <code>published
                                final</code>,
                                even if the conventional method of detecting this change failed.
                            </p>
                            <p>
                                This duration is measured starting from the time the episode was published.
                            </p>
                        </ReadMore>
                    }
                />
                <DurationField
                    id="settings-dw-processing-max"
                    label="Source processing safeguard"
                    value={draft.episodeStatusTiming.dwProcessingMaxMinutes}
                    backendUnit="minutes"
                    error={errorFor('episodeStatusTiming.dwProcessingMaxMinutes')}
                    environmentVariable={environmentVariableFor('episodeStatusTiming.dwProcessingMaxMinutes')}
                    onChange={(value) => updateDraft((next) => {
                        next.episodeStatusTiming.dwProcessingMaxMinutes = value
                    })}
                    help={
                        <ReadMore summary={<span>Treat an episode still processing at The Daily Wire after this duration as removed from it.</span>}>
                            <p>
                                Usually, VODLoft can determine an episode's status accurately. However, sometimes an episode might get stuck
                                in <code>Processing at the source</code>. Once this duration passed, VODLoft treats it like an episode The
                                Daily Wire no longer has: without files it is deleted after a few more hours, with files it is marked Removed.
                            </p>
                            <p>
                                This duration is measured starting from the time the episode was published.
                            </p>
                        </ReadMore>
                    }
                />
            </SettingsDisclosure>
        </>
    )
}
