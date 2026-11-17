import {type ReactNode, useState} from 'react'
import {Controller, type UseFormReturn} from 'react-hook-form'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import type {SelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../common/SimpleSelect'

/** "Follows Settings" while a value comes from Settings; otherwise a button that makes it follow Settings again. */
export function FollowsSettingsBadge({following, onUseSettings}: {following: boolean; onUseSettings: () => void}) {
    if (following) {
        return (
            <span className="follows-settings-badge" title="This profile uses the value in Settings. Click a box to choose your own.">
                <FontAwesomeIcon icon={faIcon('fass', 'link')}/>
                <span><span className="follows-settings-badge__long">Follows </span>Settings</span>
            </span>
        )
    }
    return (
        <button type="button" className="follows-settings-badge" onClick={onUseSettings} title="Use the value in Settings again">
            <FontAwesomeIcon icon={faIcon('fass', 'arrow-rotate-left')}/>
            <span>Use Settings</span>
        </button>
    )
}

/** A checkbox that shows the value in Settings, dashed, until the profile chooses its own. */
export function FollowCheck({id, checked, following, onChange, label, description, disabled}: {
    id: string
    checked: boolean
    following: boolean
    onChange: (checked: boolean) => void
    label: ReactNode
    description?: ReactNode
    disabled?: boolean
}) {
    return (
        <label className={`follow-check${following ? ' is-following' : ''}`} htmlFor={id}>
            <input
                id={id}
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={(event) => onChange(event.target.checked)}
            />
            {(label || description) && (
                <span className="follow-check__text">
                    {label}
                    {description && <small>{description}</small>}
                </span>
            )}
        </label>
    )
}

/**
 * A choice that can follow Settings. While it does, it is one quiet line with the value from Settings and a Change
 * button; Change shows the select, with System first.
 */
export function FollowsSettingsSelect({form, name, id, label, registry, systemLabel, help}: {
    form: UseFormReturn<any>
    name: string
    id: string
    label: string
    /** Every choice, System first. */
    registry: SelectRegistry<any>
    /** The value in Settings, in words. */
    systemLabel: string
    help: ReactNode
}) {
    const {control, formState: {errors}} = form
    const [changing, setChanging] = useState(false)
    const error = errors[name]

    return (
        <Controller
            control={control}
            name={name}
            render={({field}) => {
                const following = (field.value ?? 'system') === 'system'
                if (following && !changing && !error) {
                    return (
                        <div className="form-row">
                            <div className="follows-settings-line">
                                <span className="follows-settings-line__text">
                                    <span>{label}</span>
                                    <span className="follows-settings-line__value">{systemLabel}</span>
                                    <FollowsSettingsBadge following onUseSettings={() => undefined}/>
                                </span>
                                <button
                                    type="button"
                                    className="btn btn-small"
                                    aria-label={`Change ${label.toLowerCase()}`}
                                    onClick={() => setChanging(true)}
                                >
                                    Change
                                </button>
                            </div>
                            <div className="help">{help}</div>
                        </div>
                    )
                }
                return (
                    <div className="form-row">
                        <label htmlFor={id}>{label}</label>
                        <SimpleSelect
                            inputId={id}
                            registry={registry}
                            value={field.value ?? 'system'}
                            onChange={(value) => {
                                field.onChange(value)
                                if (value === 'system') setChanging(false)
                            }}
                            onBlur={field.onBlur}
                            autoFocus={changing && following}
                            openMenuOnFocus={changing && following}
                            aria-invalid={!!error}
                            aria-describedby={error ? `${id}-error` : `${id}-help`}
                        />
                        {error && (
                            <div id={`${id}-error`} className="error" role="alert" aria-live="polite">
                                {String(error.message)}
                            </div>
                        )}
                        <div className="help" id={`${id}-help`}>
                            {!following && (
                                <button
                                    type="button"
                                    className="link-button"
                                    onClick={() => {
                                        field.onChange('system')
                                        setChanging(false)
                                    }}
                                >
                                    <FontAwesomeIcon icon={faIcon('fass', 'arrow-rotate-left')}/> Use Settings again
                                </button>
                            )}
                            {!following && ' '}
                            {help}
                        </div>
                    </div>
                )
            }}
        />
    )
}
