import {ChosenShowCard} from './ShowPreviewCard'
import type {ShowCreatePayloadOut} from '../../types/schemas/show'
import {ShowTypeReg, ShowTypeValue} from '../../types/show'
import SeriesDownloadProfileStep from './DownloadProfileVersions/SeriesDownloadProfileStep'
import PodcastDownloadProfileStep from "./DownloadProfileVersions/PodcastDownloadProfileStep";
import {
    DownloadProfileUnifiedCreateIn, DownloadProfileUnifiedCreateOut
} from "../../types/schemas/show_as_bundle";
import {SeasonDetachedOut} from "../../types/schemas/season";


type Props = {
    value: {
        podcast: Partial<DownloadProfileUnifiedCreateIn>,
        series: Partial<DownloadProfileUnifiedCreateIn>
    }
    onChange: {
        podcast: (v: Partial<DownloadProfileUnifiedCreateIn>) => void,
        series: (v: Partial<DownloadProfileUnifiedCreateIn>) => void,
    }
    onSubmit: {
        podcast: (v: DownloadProfileUnifiedCreateOut) => void,
        series: (v: DownloadProfileUnifiedCreateOut) => void,
    }
    onBack: () => void
    onContinue: () => void
    onCancel: () => void
    showSlug?: string
    /** The show chosen in the first step. */
    show?: ShowCreatePayloadOut
    showType?: ShowTypeValue | ''
    seasons: SeasonDetachedOut[]
    continueLabel?: string
}

export default function DownloadProfileStep({value, onChange, onSubmit, onBack, onContinue, onCancel, show, showType, seasons, continueLabel}: Props) {
    // Return the appropriate step component based on the show type
    return (
        <div className="wizard-with-aside">
            <div className="wizard-main">
                {showType === ShowTypeReg.Enum.podcast ? (
                    <PodcastDownloadProfileStep
                        value={value.podcast}
                        onChange={onChange.podcast}
                        onSubmit={onSubmit.podcast}
                        onBack={onBack}
                        onContinue={onContinue}
                        onCancel={onCancel}
                        continueLabel={continueLabel}
                        sourceKey={show?.sourceKey}
                    />
                ) : (
                    <SeriesDownloadProfileStep
                        value={value.series}
                        onChange={onChange.series}
                        onSubmit={onSubmit.series}
                        seasons={seasons}
                        onBack={onBack}
                        onContinue={onContinue}
                        onCancel={onCancel}
                        continueLabel={continueLabel}
                    />
                )}
            </div>

            {show ? (
                <aside className="wizard-aside" aria-label="Selected show details">
                    <ChosenShowCard show={show}/>
                </aside>
            ) : null}
        </div>
    )
}
