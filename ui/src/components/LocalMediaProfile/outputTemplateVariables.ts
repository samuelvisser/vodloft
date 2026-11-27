import type {LocalMediaProfileMode} from './LocalMediaProfileForm'

export type OutputTemplateVariableReadMore = {
    summary?: string
    paragraphs: readonly string[]
}

export type OutputTemplateVariable = {
    name: string
    description: string
    /** A few words for the template reference; the description shows when the row is pointed at or tapped. */
    short?: string
    readMore?: OutputTemplateVariableReadMore
}

const DATE_VARIABLES: readonly OutputTemplateVariable[] = [
    {name: 'date', description: 'Date as YYYY-MM-DD'},
    {name: 'time', description: 'Time as HH:MM:SS'},
    {name: 'datetime', description: 'Date and time'},
    {name: 'year', description: 'Four-digit year'},
    {name: 'month', description: 'Two-digit month'},
    {name: 'day', description: 'Two-digit day'},
    {name: 'hour', description: 'Two-digit hour'},
    {name: 'minute', description: 'Two-digit minute'},
    {name: 'second', description: 'Two-digit second'},
    {name: 'day_of_year', description: 'Three-digit day of the year, 001 on 1 January', short: 'Day of the year, 001'},
    {name: 'day_of_year_reversed', description: 'Three-digit day of the year counted back, 001 on 31 December, so newer days sort first', short: 'Day of the year counted back'},
]

const COLLECTION_VARIABLES: readonly OutputTemplateVariable[] = [
    {name: 'collection', description: 'Collection URL slug'},
    {name: 'collection_title', description: 'Collection title'},
    {name: 'collection_author', description: 'Collection author, host or channel name', short: 'Author, host or channel'},
    {name: 'collection_site_id', description: 'The id the site gives the collection, such as a YouTube channel or playlist id', short: 'The site\'s own id'},
    {name: 'season', description: 'Season URL slug'},
    {name: 'season_name', description: 'Season name'},
    {name: 'season_index', description: 'VODLoft internal season index', short: 'Internal season index'},
    {
        name: 'season_type',
        description: 'Season type: normal or extra', short: 'normal or extra',
        readMore: {
            paragraphs: [
                'VODLoft attempts to classify whether a season is regular or extra based on it\'s title. ' +
                'Use this value in Jinja conditions when normal and extra seasons need different paths.',
                '<strong>normal</strong> season contains regular collection episodes',
                '<strong>extra</strong> season contains extra\'s for the collection'
            ],
        },
    },
    {
        name: 'season_number',
        description: 'Stable media season number; Extras seasons use 0', short: 'Season number; extras 0',
        readMore: {
            paragraphs: [
                'Normal seasons use their stable media-facing season number, while every extras season uses 0.',
                'Unlike the internal season_index, this value is designed for media-server paths and is not affected by where extras seasons appear in the source\'s season list.',
            ],
        },
    },
    {name: 'episode', description: 'Episode URL slug'},
    {name: 'episode_title', description: 'Episode title'},
    {name: 'title', description: 'Episode title'},
    {name: 'episode_site_id', description: 'The id the site gives the episode, such as a YouTube video id', short: 'The site\'s own id'},
    {name: 'episode_uploader', description: 'Who uploaded the episode, when the site says; empty otherwise', short: 'Who uploaded it'},
    {name: 'duration_seconds', description: 'Episode duration in whole seconds', short: 'Length in seconds'},
    {name: 'site_number', description: 'The episode\'s number as its site writes it, such as 2460.10 on The Daily Wire or 12 on NPO Start; empty on sites that do not number their episodes', short: 'Number as the site gives it'},
    {
        name: 'episode_type',
        description: 'Episode type: ep for a normal episode, or a type the site gives its other content', short: 'ep, or the site\'s own type',
        readMore: {
            paragraphs: [
                'Every site uses <strong>ep</strong> for its normal episodes. Other content gets a type of its own, ' +
                'depending on the site. Use <code>episode_type != \'ep\'</code> to match all of them at once.',
                '<strong>ep</strong> a normal episode, on every site (a normal video on YouTube)',
                '<strong>ep-extra</strong> extra content for one episode (The Daily Wire)',
                '<strong>trailer</strong> a trailer for the show or its extra content (The Daily Wire)',
                '<strong>aux</strong> auxiliary content for the show (The Daily Wire)',
                '<strong>short</strong> a YouTube Short (YouTube)',
                '<strong>livestream</strong> a livestream, upcoming, live or finished (YouTube)',
            ],
        },
    },
    {name: 'episode_extra_type', description: 'Episode-extra subtype: other or trailer; empty otherwise', short: 'other or trailer'},
    {
        name: 'episode_index',
        description: 'VODLoft episode index across the whole collection, including extras', short: 'Number across the collection',
        readMore: {
            paragraphs: [
                'VODLoft\'s internal episode index, in ascending order.',
                'Unlike <code>episode_number</code>, it does not restart for a season or episode type. It is the stored Episode index, ' +
                'not a database ID or a newly calculated counter. Gaps caused by episodes that disappear from their Source ' +
                'are preserved.',
                'In most cases, it is better practice to use this index value instead of a custom index if your goal is ' +
                'to number every episode in a collection in order. However, custom indexes do automatically reconcile in the ' +
                'case of an episode getting deleted in the middle of the collection, which makes them slightly different.',

            ],
        },
    },
    {
        name: 'extra_index',
        description: 'VODLoft number for an extra, counted across the whole collection; empty for normal episodes', short: 'Number of an extra',
        readMore: {
            paragraphs: [
                'An extra is an episode of an Extras season, or an episode of any type other than <strong>ep</strong>, ' +
                'such as an auxiliary episode, a trailer, an episode extra or a YouTube Short. This is the same as ' +
                '<code>season_type == \'extra\' or episode_type != \'ep\'</code>.',
                'All extras of a collection share one count, in the order of their <code>episode_index</code>, so no two ' +
                'extras get the same number. That makes it a good fit for a Specials season in a media server.',
                'An extra keeps its number once VODLoft gave it one, so its files keep their names. A new extra takes the ' +
                'next number, and an episode that stops being an extra leaves a gap.',
            ],
        },
    },
    {name: 'episode_number', description: 'Episode number. An episode extra has its episode\'s number; other types count on their own', short: 'Episode number'},
    {name: 'episode_sub_number', description: 'The source\'s sub-episode number for episode extras; empty otherwise', short: 'Sub-number of an extra'},
    {name: 'episode_label', description: 'Canonical label without the type prefix (e.g. 2497, 2497.1, S01E07, S01E07.1)', short: '2497.1 or S01E07'},
    {
        name: 'episode_identifier',
        description: 'Guaranteed unique VODLoft episode identifier', short: 'Always unique',
        readMore: {
            paragraphs: [
                'The full VODLoft episode identifier includes the type prefix, making it guaranteed unique within the collection.',
                'This is mainly meant for VODLoft internal usage, but can be handy nevertheless due to its guaranteed unique nature for naming files.'
            ]
        }
    },
    {name: 'episode_published_date', description: 'Published date as YYYY-MM-DD', short: '2026-03-05'},
    {name: 'episode_published_time', description: 'Published time as HH:MM:SS', short: '14:30:00'},
    {name: 'episode_published_datetime', description: 'Published date and time'},
    {
        name: 'creator_title',
        description: 'Name of the creator or host the collection was added with', short: 'Creator or host',
        readMore: {
            paragraphs: [
                'Empty for a collection that was not added with a creator. ' +
                'Put it in the path, such as {{ creator_title }}/{{ collection_title }}, to file shows by their creator.',
            ],
        },
    },
    {name: 'creator_handle', description: 'The creator\'s handle without the @, such as northwindworkshop', short: 'Handle, without the @'},
    {name: 'creator_kind', description: 'What the site calls the creator, such as YouTube creator or The Daily Wire host', short: 'What the site calls them'},
    {name: 'section_title', description: 'The part of the creator that listed the episode, such as Videos or a playlist', short: 'Videos, or a playlist'},
    {name: 'section_kind', description: 'feed, list or item'},
    {
        name: 'artist',
        description: 'Who the music is by: the creator, else the collection\'s author', short: 'Who the music is by',
        readMore: {
            paragraphs: [
                'Meant for profiles for Music that download audio only, such as {{ artist }}/{{ year }} - {{ album }}/{{ track_number_padded }} - {{ title }}.',
            ],
        },
    },
    {name: 'album', description: 'The episode\'s season when it holds one playlist or album, else the collection\'s title', short: 'Album or playlist'},
    {name: 'album_slug', description: 'Album URL slug, the same as season', short: 'Album URL slug'},
    {name: 'album_number', description: 'The album\'s number, the same as season_number; Extras use 0', short: 'Album number; extras 0'},
    {name: 'track_number', description: 'The episode\'s number on its album, such as 3', short: 'Number on its album, 3'},
    {name: 'track_number_padded', description: 'The track number with two digits, such as 03', short: 'Track number, 03'},
    ...DATE_VARIABLES,
]

// A Video profile keeps single videos, and movies with their extras.
const VIDEO_VARIABLES: readonly OutputTemplateVariable[] = [
    {name: 'title', description: 'Title of the video, movie or extra'},
    {name: 'slug', description: 'The site\'s own id for the video, movie or extra', short: 'The site\'s own id'},
    {name: 'extended_title', description: 'Full title of the video, movie or extra', short: 'Full title'},
    {name: 'author', description: 'Channel, uploader or movie author, when the site names one', short: 'Channel or uploader'},
    {name: 'source', description: 'Name of the site it comes from', short: 'Site name'},
    {name: 'duration_seconds', description: 'Duration in seconds'},
    {name: 'media_type', description: 'video, movie, trailer, interview, or another extra type', short: 'video, movie, trailer…'},
    {name: 'mature_rating', description: 'Movie rating; empty for videos and extras', short: 'Movie rating'},
    {name: 'rating', description: 'Movie rating; empty for videos and extras', short: 'Movie rating'},
    {name: 'date', description: 'Upload or release date as YYYY-MM-DD'},
    {name: 'time', description: 'Upload or release time as HH:MM:SS'},
    {name: 'datetime', description: 'Upload or release date and time'},
    {name: 'year', description: 'Upload or release year'},
    {name: 'month', description: 'Upload or release month'},
    {name: 'day', description: 'Upload or release day'},
    {name: 'hour', description: 'Upload or release hour'},
    {name: 'minute', description: 'Upload or release minute'},
    {name: 'second', description: 'Upload or release second'},
    {name: 'day_of_year', description: 'Upload or release day of the year, 001 on 1 January', short: 'Day of the year, 001'},
    {name: 'day_of_year_reversed', description: 'Upload or release day of the year counted back, 001 on 31 December', short: 'Day of the year counted back'},
    {name: 'movie_title', description: 'Parent movie title; empty for a single video', short: 'Movie title'},
    {name: 'movie_slug', description: 'Parent movie URL slug; empty for a single video', short: 'Movie URL slug'},
    {name: 'movie_extended_title', description: 'Parent movie full title; empty for a single video', short: 'Movie full title'},
    {name: 'movie_author', description: 'Parent movie author or host; empty for a single video', short: 'Movie author or host'},
    {name: 'movie_mature_rating', description: 'Parent movie rating; empty for a single video', short: 'Movie rating'},
    {name: 'movie_duration_seconds', description: 'Parent movie runtime in seconds; empty for a single video', short: 'Movie length in seconds'},
    {name: 'movie_date', description: 'Parent movie release date as YYYY-MM-DD'},
    {name: 'movie_time', description: 'Parent movie release time as HH:MM:SS'},
    {name: 'movie_datetime', description: 'Parent movie release date and time'},
    {name: 'movie_year', description: 'Parent movie release year'},
    {name: 'movie_month', description: 'Parent movie release month'},
    {name: 'movie_day', description: 'Parent movie release day'},
    {name: 'movie_hour', description: 'Parent movie release hour'},
    {name: 'movie_minute', description: 'Parent movie release minute'},
    {name: 'movie_second', description: 'Parent movie release second'},
    {name: 'movie_day_of_year', description: 'Parent movie release day of the year'},
    {name: 'movie_day_of_year_reversed', description: 'Parent movie release day of the year counted back', short: 'Day of the year counted back'},
]

const VARIABLES_BY_MODE: Record<LocalMediaProfileMode, readonly OutputTemplateVariable[]> = {
    collection: COLLECTION_VARIABLES,
    video: VIDEO_VARIABLES,
}

/** The numbers VODLoft keeps for every episode, which the template help lists as built-in Indexing values. */
export const BUILT_IN_INDEXING_VALUES: ReadonlySet<string> = new Set(['episode_index', 'extra_index'])

// A Music collection's albums are its seasons. A profile for Music lists them as albums, by
// the album_* names that hold the same values, and every other Collection profile lists them as seasons.
const SEASON_VARIABLES: ReadonlySet<string> = new Set(['season', 'season_name', 'season_number'])
const ALBUM_VARIABLES: ReadonlySet<string> = new Set(['album_slug', 'album_number'])

export function getOutputTemplateVariables(
    mode: LocalMediaProfileMode,
    customVariables: readonly OutputTemplateVariable[] = [],
    collectionScope?: string,
): readonly OutputTemplateVariable[] {
    const music = mode === 'collection' && collectionScope === 'music'
    const baseVariables = VARIABLES_BY_MODE[mode].filter((variable) => (
        music ? !SEASON_VARIABLES.has(variable.name) : !ALBUM_VARIABLES.has(variable.name)
    ))
    const merged = new Map(baseVariables.map((variable) => [variable.name, variable]))
    for (const variable of customVariables) merged.set(variable.name, variable)
    return [...merged.values()]
}
