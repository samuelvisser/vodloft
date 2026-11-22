import Switch from 'react-switch'
import SimpleSelect from '../common/SimpleSelect'
import {useCreators} from '../../lib/queries'
import {BEHIND_LINK, useCreatorTargets} from '../Creator/creatorTargets'
import type {Names} from '../../types/schemas/source'

/** Whether the new channel collection is added to a creator, and to which. */
export type CreatorChoice = {on: boolean, target: string}
export const NO_CREATOR: CreatorChoice = {on: false, target: BEHIND_LINK}

/** "Add to a creator" on the first page of the Add Collection wizard, for a channel on a Site with creators. Off
 *  until the user switches it on; the collection joins once it is added. */
export default function CreatorSwitch({creatorNames, value, onChange}: {
    /** What the collection calls the creator behind it, such as host, or artist in a Music collection. */
    creatorNames: Names
    value: CreatorChoice
    onChange: (value: CreatorChoice) => void
}) {
    const {data: creators} = useCreators()
    const targets = useCreatorTargets('wizard', creatorNames, creators)
    return (
        <div className="form-row">
            <label className="seasons-dialog-check" htmlFor="collection-creator-on">
                <Switch
                    id="collection-creator-on" checked={value.on} onChange={(on) => onChange({...value, on})}
                    onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
                    height={18} width={34} handleDiameter={14}
                />
                <span><b>Add to {creatorNames.a}</b></span>
            </label>
            {value.on && (creators?.length ?? 0) > 0 && (
                <SimpleSelect
                    inputId="collection-creator-target" aria-label={`Which ${creatorNames.singular}`} registry={targets} value={value.target}
                    onChange={(target) => onChange({...value, target: target ?? BEHIND_LINK})}
                />
            )}
            <div className="help">
                {value.on
                    ? value.target === BEHIND_LINK
                        ? `VODLoft adds the ${creatorNames.singular} behind the link to your library, or finds them there, and groups the collection under them.`
                        : `The collection is grouped under that ${creatorNames.singular} in your library.`
                    : `${creatorNames.a[0].toUpperCase()}${creatorNames.a.slice(1)} groups their collections in your library. You can also add the collection to one later, from its page.`}
            </div>
        </div>
    )
}
