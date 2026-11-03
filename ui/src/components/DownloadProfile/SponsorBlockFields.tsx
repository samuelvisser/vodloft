import {useWatch, type UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'

import {
    DEFAULT_SPONSORBLOCK_SEGMENTS, SPONSORBLOCK_COLORS, SPONSORBLOCK_GROUPS, SponsorBlockActionReg, SponsorBlockCategoryReg,
} from '../../types/sponsorblock'
import ReadMore from '../../utils/ReadMore'

/** SponsorBlock on a YouTube Download Profile: a switch, and Keep, Chapter or Cut out per segment type. */
export default function SponsorBlockFields({form}: {form: UseFormReturn<any>}) {
    const {control, setValue} = form
    const [enabledValue, segmentsValue] = useWatch({control, name: ['sponsorblockEnabled', 'sponsorblockSegments']}) as [boolean | undefined, Record<string, string> | undefined]
    const enabled = enabledValue ?? true
    const segments = {...DEFAULT_SPONSORBLOCK_SEGMENTS, ...(segmentsValue ?? {})}

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
                <table className="sponsorblock-grid">
                    <thead>
                    <tr>
                        <th scope="col"><span className="sr-only">Segment type</span></th>
                        {SponsorBlockActionReg.values.map((action) => (
                            <th key={action} scope="col">{SponsorBlockActionReg.getLabel(action)}</th>
                        ))}
                    </tr>
                    </thead>
                    {SPONSORBLOCK_GROUPS.map((group) => (
                        <tbody key={group.label}>
                        <tr className="sponsorblock-grid__group"><th colSpan={4} scope="rowgroup">{group.label}</th></tr>
                        {group.categories.map((category) => (
                            <tr key={category}>
                                <th scope="row">
                                    <span className="sponsorblock-grid__name">
                                        <span className="sponsorblock-swatch" style={{background: SPONSORBLOCK_COLORS[category]}} aria-hidden="true"/>
                                        {SponsorBlockCategoryReg.getLabel(category)}
                                    </span>
                                    <small>{SponsorBlockCategoryReg.getHelp(category)}</small>
                                </th>
                                {SponsorBlockActionReg.values.map((action) => (
                                    <td key={action}>
                                        <input
                                            type="radio"
                                            name={`sponsorblock-${category}`}
                                            aria-label={`${SponsorBlockCategoryReg.getLabel(category)}: ${SponsorBlockActionReg.getLabel(action)}`}
                                            checked={segments[category] === action}
                                            onChange={() => choose(category, action)}
                                        />
                                    </td>
                                ))}
                            </tr>
                        ))}
                        </tbody>
                    ))}
                </table>
            )}
            <div className="help" id="sponsorblock-help">
                <ReadMore summary="Mark or cut out sponsor reads and other parts of a video.">
                    <p>SponsorBlock is a community database of parts of YouTube videos, such as sponsor reads and “like and subscribe” reminders.
                        A part becomes a chapter your player can skip, or is cut out of the file. Most parts are submitted in the days after a video comes out,
                        so a download right after upload may have few of them. The episode page shows what was found.</p>
                    <p><strong>Chapter</strong> is the safe choice: nothing is removed, and your player can skip it.
                        {' '}<strong>Cut out</strong> is final; the cut part isn’t kept anywhere. SponsorBlock’s Highlight is always a chapter.</p>
                </ReadMore>
            </div>
        </div>
    )
}
