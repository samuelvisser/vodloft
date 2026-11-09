import {useWatch, type UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'

import {
    SPONSORBLOCK_COLORS, SPONSORBLOCK_GROUPS, SponsorBlockActionReg, SponsorBlockCategoryReg, sponsorBlockActionReg,
} from '../../types/sponsorblock'
import ReadMore from '../../utils/ReadMore'

/** SponsorBlock on a YouTube Download Profile: a switch, and Keep, Chapter or Cut out per segment type. */
export default function SponsorBlockFields({form}: {form: UseFormReturn<any>}) {
    const {control, setValue} = form
    const [enabled, segments] = useWatch({control, name: ['sponsorblockEnabled', 'sponsorblockSegments']}) as [boolean, Record<string, string>]

    const choose = (category: string, action: string) =>
        setValue('sponsorblockSegments', {...segments, [category]: action}, {shouldDirty: true})

    return (
        <div className="form-row">
            <label htmlFor="sponsorblock-enabled">Use SponsorBlock</label>
            <Switch
                id="sponsorblock-enabled"
                checked={enabled}
                onChange={(value) => setValue('sponsorblockEnabled', value, {shouldDirty: true})}
                onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
                aria-describedby="sponsorblock-help"
            />
            {enabled && (
                <div className="sponsorblock-groups">
                    {SPONSORBLOCK_GROUPS.map((group) => (
                        <fieldset key={group.label} className="sponsorblock-group">
                            <legend>{group.label}</legend>
                            {group.categories.map((category) => {
                                const label = SponsorBlockCategoryReg.getLabel(category)
                                const help = SponsorBlockCategoryReg.getHelp(category)
                                return (
                                    <div key={category} className="sponsorblock-row">
                                        <span className="sponsorblock-row__name" id={`sponsorblock-${category}-label`} title={help}>
                                            <span className="sponsorblock-swatch" style={{background: SPONSORBLOCK_COLORS[category]}} aria-hidden="true"/>
                                            {label}
                                        </span>
                                        <span className="sr-only" id={`sponsorblock-${category}-help`}>{help}</span>
                                        <span
                                            className="sponsorblock-choice"
                                            role="radiogroup"
                                            aria-labelledby={`sponsorblock-${category}-label`}
                                            aria-describedby={`sponsorblock-${category}-help`}
                                        >
                                            {sponsorBlockActionReg(category).values.map((action) => (
                                                <label key={action} title={SponsorBlockActionReg.getHelp(action)}>
                                                    <input
                                                        type="radio"
                                                        name={`sponsorblock-${category}`}
                                                        value={action}
                                                        aria-label={`${label}: ${SponsorBlockActionReg.getLabel(action)}`}
                                                        checked={segments[category] === action}
                                                        onChange={() => choose(category, action)}
                                                    />
                                                    <span>{SponsorBlockActionReg.getLabel(action)}</span>
                                                </label>
                                            ))}
                                        </span>
                                    </div>
                                )
                            })}
                        </fieldset>
                    ))}
                </div>
            )}
            <div className="help" id="sponsorblock-help">
                <ReadMore summary="Mark or cut out sponsor reads and other parts of a video.">
                    <p>SponsorBlock is a community database of parts of YouTube videos, such as sponsor reads and “like and subscribe” reminders.
                        A part becomes a chapter your player can skip, or is cut out of the file. Most parts are submitted in the days after a video comes out,
                        so a download right after upload may have few of them. The episode page shows what was found.</p>
                    <p><strong>Chapter</strong> is the safe choice: nothing is removed, and your player can skip it.
                        {' '}<strong>Cut out</strong> is final; the cut part isn’t kept anywhere. The Highlight and viewer chapters mark a moment or name a part, so they can only be kept or made a chapter.</p>
                </ReadMore>
            </div>
        </div>
    )
}
