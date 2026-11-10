import Switch from 'react-switch'

import {
    SPONSORBLOCK_COLORS, SPONSORBLOCK_GROUPS, SponsorBlockActionReg, SponsorBlockCategoryReg, sponsorBlockActionReg,
} from '../../types/sponsorblock'
import ReadMore from '../../utils/ReadMore'

type Props = {
    /** Keeps the ids of each Site's fields apart. */
    idPrefix: string
    enabled: boolean
    segments: Record<string, string>
    onChange: (enabled: boolean, segments: Record<string, string>) => void
    /** Which of the profile's Sites have SponsorBlock, as in "Applies to YouTube." */
    appliesTo: string
}

/** SponsorBlock on a Local Media Profile: a switch, and Keep, Chapter or Cut out per segment type. */
export default function SponsorBlockFields({idPrefix, enabled, segments, onChange, appliesTo}: Props) {
    const choose = (category: string, action: string) => onChange(enabled, {...segments, [category]: action})

    return (
        <div className="form-row">
            <label htmlFor={`${idPrefix}-sponsorblock-enabled`}>Use SponsorBlock</label>
            <Switch
                id={`${idPrefix}-sponsorblock-enabled`}
                checked={enabled}
                onChange={(value) => onChange(value, segments)}
                onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
                aria-describedby={`${idPrefix}-sponsorblock-help`}
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
                                        <span className="sponsorblock-row__name" id={`${idPrefix}-sponsorblock-${category}-label`} title={help}>
                                            <span className="sponsorblock-swatch" style={{background: SPONSORBLOCK_COLORS[category]}} aria-hidden="true"/>
                                            {label}
                                        </span>
                                        <span className="sr-only" id={`${idPrefix}-sponsorblock-${category}-help`}>{help}</span>
                                        <span
                                            className="sponsorblock-choice"
                                            role="radiogroup"
                                            aria-labelledby={`${idPrefix}-sponsorblock-${category}-label`}
                                            aria-describedby={`${idPrefix}-sponsorblock-${category}-help`}
                                        >
                                            {sponsorBlockActionReg(category).values.map((action) => (
                                                <label key={action} title={SponsorBlockActionReg.getHelp(action)}>
                                                    <input
                                                        type="radio"
                                                        name={`${idPrefix}-sponsorblock-${category}`}
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
            <div className="help" id={`${idPrefix}-sponsorblock-help`}>
                <ReadMore summary={`Mark or cut out sponsor reads and other parts of a video. ${appliesTo}`}>
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
