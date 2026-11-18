import {createSelectRegistry} from '../../utils/selectRegistry'

/** What choosing a preset sets on a Collection Local Media Profile besides its output template. */
type PresetChoices = {
    metadataMode: 'embed' | 'embed_and_nfo'
    showNfo: boolean
    kodiSafeNfo: boolean
    fileDateFromPublishDate: boolean
}

type Preset = {
    template: (base: string) => string
    choices: PresetChoices
    /** An Indexing Value the template numbers extras with, added to the profile when it has none of that key. */
    indexingValue?: {key: string, name: string, keepNumbers: boolean}
}

// Season and episode as two digits, and whether an episode belongs with the specials.
const NUMBERS = `{% set season_num = "%02d"|format(season_number|int) %}
{% set ep_num = "%02d"|format(episode_number|int) %}
{% set is_extra = season_type == 'extra' or episode_type == 'aux' or episode_type == 'trailer' %}`

const EXTRAS = {key: 'extra', name: 'Extras', keepNumbers: true}

// Jellyfin, Emby and Kodi name shows the same way, and read the show and season NFO files.
const nfoServerTemplate = (base: string) => `{# Variables #}
${NUMBERS}
{% set season_folder = 'Season 00' if is_extra else 'Season ' ~ season_num %}
{% set episode_id %}
	{% if is_extra %}
		S00E{{ "%02d"|format('extra' | custom_index) }}
	{% else %}
		S{{ season_num }}E{{ ep_num }}
	{% endif %}
{% endset %}

{# Path #}
${base}
/{{ collection_title }}
/{{ season_folder }}
/{{ collection_title }} {{ episode_id }} {{ title }}.ext`

const PRESETS: Record<string, Preset> = {
    plex: {
        template: (base) => `{# Variables #}
${NUMBERS}
{% set plex_season = 'Specials' if is_extra else 'Season ' ~ season_num %}
{% set plex_ep_id %}
	{% if is_extra %}
		other{{ 'extra' | custom_index }}
	{% else %}
		S{{ season_num }}E{{ ep_num }}
	{% endif %}
{% endset %}
{# Plex reads a number such as 4x4 in a title as the season/episode #}
{% set plex_title = title | replace('[', '(') | replace(']', ')') | regex_replace('(?<=\\d)[xX](?=\\d)', '-by-') %}

{# Path #}
${base}
/{{ collection_title }}
/{{ plex_season }}
/{{ collection_title }} - {{ plex_ep_id }} [{{ plex_title }}].ext`,
        choices: {metadataMode: 'embed', showNfo: false, kodiSafeNfo: false, fileDateFromPublishDate: true},
        indexingValue: EXTRAS,
    },
    jellyfin: {
        template: nfoServerTemplate,
        choices: {metadataMode: 'embed_and_nfo', showNfo: true, kodiSafeNfo: false, fileDateFromPublishDate: true},
        indexingValue: EXTRAS,
    },
    kodi: {
        template: nfoServerTemplate,
        choices: {metadataMode: 'embed_and_nfo', showNfo: true, kodiSafeNfo: true, fileDateFromPublishDate: true},
        indexingValue: EXTRAS,
    },
    audiobookshelf: {
        template: (base) => `${base}
/{{ collection_title }}
/{% if episode_published_date %}{{ episode_published_date }} - {% endif %}{{ title }}.ext`,
        choices: {metadataMode: 'embed', showNfo: false, kodiSafeNfo: false, fileDateFromPublishDate: true},
    },
}

const PRESET_NAMES = {
    jellyfin: {label: 'Jellyfin and Emby'},
    kodi: {label: 'Kodi'},
    audiobookshelf: {label: 'Audiobookshelf'},
    plex: {label: 'Plex'},
} as const

const VideoPresetReg = createSelectRegistry('OutputTemplatePreset', {
    jellyfin: PRESET_NAMES.jellyfin, kodi: PRESET_NAMES.kodi, plex: PRESET_NAMES.plex,
})
const AudioPresetReg = createSelectRegistry('OutputTemplatePreset', {
    audiobookshelf: PRESET_NAMES.audiobookshelf, jellyfin: PRESET_NAMES.jellyfin, kodi: PRESET_NAMES.kodi,
    plex: PRESET_NAMES.plex,
})

/** The presets a profile can start from: Audiobookshelf only keeps audio. */
export function outputTemplatePresetRegistry(audioOnly: boolean) {
    return audioOnly ? AudioPresetReg : VideoPresetReg
}

/** The folder a template keeps its files under, before the first part that changes per episode. */
export function templateBaseFolder(template: string, fallback: string): string {
    const start = template.indexOf('/downloads')
    if (start < 0) return fallback
    const rest = template.slice(start).replace(/\s*\n\s*/g, '')
    const jinja = rest.search(/\{[{%#]/)
    const literal = jinja < 0 ? rest : rest.slice(0, jinja)
    return literal.slice(0, literal.lastIndexOf('/')) || '/downloads'
}

export function outputTemplatePreset(key: string): Preset | undefined {
    return PRESETS[key]
}
