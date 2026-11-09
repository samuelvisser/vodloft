import {createSelectRegistry} from '../utils/selectRegistry'

/** SponsorBlock's segment types, in the order the Download Profile shows them. */
export const SponsorBlockCategoryReg = createSelectRegistry('SponsorBlockCategory', {
    sponsor: {label: 'Sponsor', help: 'Paid promotion and ad reads.'},
    selfpromo: {label: 'Self-promotion', help: 'Merchandise, Patreon and the creator’s other channels.'},
    interaction: {label: 'Interaction reminder', help: '“Like and subscribe” and similar asks.'},
    intro: {label: 'Intro', help: 'An intro animation or a pause without content.'},
    outro: {label: 'Outro', help: 'End cards and credits.'},
    preview: {label: 'Preview and recap', help: 'Clips of what is coming up or what happened before.'},
    filler: {label: 'Filler', help: 'Tangents and jokes that are not needed for the main content.'},
    hook: {label: 'Hook and greetings', help: 'The teaser and “hey everyone, welcome back” at the start.'},
    music_offtopic: {label: 'Non-music section', help: 'Only in music videos: the parts that are not music.'},
    poi_highlight: {label: 'Highlight', help: 'The moment viewers mark as where the video gets going. A single point, so it can’t be cut out.'},
    chapter: {label: 'Viewer chapters', help: 'Chapter titles viewers wrote, mostly for videos without chapters of their own. They name parts of the video, so they can’t be cut out.'},
})
export type SponsorBlockCategory = (typeof SponsorBlockCategoryReg)['values'][number]

export const SponsorBlockActionReg = createSelectRegistry('SponsorBlockAction', {
    keep: {label: 'Keep', help: 'Left as it is.'},
    chapter: {label: 'Chapter', help: 'A named chapter your player can skip. Nothing is removed.'},
    cut: {label: 'Cut out', help: 'Removed from the file for good.'},
})
export type SponsorBlockAction = (typeof SponsorBlockActionReg)['values'][number]

/** The choices for the Highlight and viewer chapters: they mark a moment or name a part, so there is nothing to cut out. */
const SponsorBlockPointActionReg = createSelectRegistry('SponsorBlockPointAction', {
    keep: SponsorBlockActionReg.meta('keep'),
    chapter: SponsorBlockActionReg.meta('chapter'),
})

/** The choices a segment type has: Keep, Chapter or Cut out, or only Keep or Chapter for the Highlight and viewer chapters. */
export function sponsorBlockActionReg(category: string) {
    return category === 'poi_highlight' || category === 'chapter' ? SponsorBlockPointActionReg : SponsorBlockActionReg
}

/** The groups the SponsorBlock cards show the segment types in. */
export const SPONSORBLOCK_GROUPS: {label: string; categories: SponsorBlockCategory[]}[] = [
    {label: 'Ads and asks', categories: ['sponsor', 'selfpromo', 'interaction']},
    {label: 'Around the content', categories: ['intro', 'outro', 'preview', 'hook']},
    {label: 'Other', categories: ['filler', 'music_offtopic', 'poi_highlight', 'chapter']},
]

/** SponsorBlock's own colour for each segment type, as its browser extension shows them. */
export const SPONSORBLOCK_COLORS: Record<string, string> = {
    sponsor: '#00d400',
    selfpromo: '#ffff00',
    interaction: '#cc00ff',
    intro: '#00ffff',
    outro: '#0202ed',
    preview: '#008fd6',
    filler: '#7300ff',
    hook: '#395699',
    music_offtopic: '#ff9900',
    poi_highlight: '#ff1684',
    chapter: '#ffd679',
}

/** A new YouTube Download Profile makes chapters of sponsors, intros, outros and the highlight and keeps everything else. */
export const DEFAULT_SPONSORBLOCK_SEGMENTS: Record<SponsorBlockCategory, SponsorBlockAction> = {
    sponsor: 'chapter',
    selfpromo: 'keep',
    interaction: 'keep',
    intro: 'chapter',
    outro: 'chapter',
    preview: 'keep',
    filler: 'keep',
    hook: 'keep',
    music_offtopic: 'keep',
    poi_highlight: 'chapter',
    chapter: 'keep',
}

export function sponsorBlockLabel(category: string): string {
    return SponsorBlockCategoryReg.getLabelLoose(category)
}
