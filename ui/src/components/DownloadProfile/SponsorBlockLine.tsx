import {useRef, useState} from 'react'
import {useWatch, type UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {
    DEFAULT_SPONSORBLOCK_SEGMENTS, SPONSORBLOCK_COLORS, SPONSORBLOCK_GROUPS, SponsorBlockActionReg, SponsorBlockCategoryReg,
    sponsorBlockSentence,
} from '../../types/sponsorblock'
import './SponsorBlockLine.css'

type Saved = {enabled: boolean; segments: Record<string, string>}

/** SponsorBlock on a YouTube Download Profile: a switch, and Keep, Chapter or Cut out per segment type. */
export default function SponsorBlockLine({form}: {form: UseFormReturn<any>}) {
    const {control, getValues, setValue} = form
    const [enabledValue, segmentsValue] = useWatch({control, name: ['sponsorblockEnabled', 'sponsorblockSegments']}) as [boolean | undefined, Record<string, string> | undefined]
    const enabled = enabledValue ?? true
    const segments = {...DEFAULT_SPONSORBLOCK_SEGMENTS, ...(segmentsValue ?? {})}
    const [open, setOpen] = useState(false)
    const before = useRef<Saved | null>(null)

    const toggle = () => {
        if (open) {
            if (before.current !== null) {
                setValue('sponsorblockEnabled', before.current.enabled, {shouldDirty: true})
                setValue('sponsorblockSegments', before.current.segments, {shouldDirty: true})
            }
            setOpen(false)
        } else {
            before.current = {enabled: getValues('sponsorblockEnabled') ?? true, segments: {...segments}}
            setOpen(true)
        }
    }
    const choose = (category: string, action: string) =>
        setValue('sponsorblockSegments', {...segments, [category]: action}, {shouldDirty: true})

    return (
        <li className={`which-episodes-line${open ? ' is-open' : ''}`}>
            <div className="which-episodes-sentence" onClick={(event) => {
                if (!(event.target as HTMLElement).closest('button, input')) toggle()
            }}>
                <span className="which-episodes-text">
                    <b>SponsorBlock</b>: {sponsorBlockSentence(enabled, segments).replace(/^./, (first) => first.toLowerCase())}
                </span>
                <button type="button" className={`which-episodes-icon${open ? ' is-active' : ''}`} aria-label="Edit SponsorBlock" aria-expanded={open} onClick={toggle}>
                    <FontAwesomeIcon icon={faIcon('fass', 'pen')}/>
                </button>
            </div>
            {open && (
                <div className="which-episodes-editor">
                    <label className="sponsorblock-switch">
                        <Switch
                            checked={enabled}
                            aria-label="Use SponsorBlock"
                            onChange={(value) => setValue('sponsorblockEnabled', value, {shouldDirty: true})}
                            onColor="#0ea5e9" offColor="#94a3b8" uncheckedIcon={false} checkedIcon={false}
                            height={20} width={38} handleDiameter={16}
                        />
                        <span>Use SponsorBlock</span>
                    </label>
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
                    <p className="which-episodes-muted sponsorblock-note">
                        <strong>Chapter</strong> is the safe choice: nothing is removed, and your player can skip it.
                        {' '}<strong>Cut out</strong> is final; the cut part isn’t kept anywhere. SponsorBlock’s Highlight is always a chapter.
                    </p>
                    <div className="which-episodes-editor-actions">
                        <button type="button" className="btn" onClick={toggle}>Cancel</button>
                        <button type="button" className="btn btn-primary" onClick={() => setOpen(false)}>Done</button>
                    </div>
                </div>
            )}
        </li>
    )
}
