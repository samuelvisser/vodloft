import {LocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import {LocalMediaProfileTypeReg, PreferredFormatReg} from "../../types/local_media_profile";
import OpaqueOutputTemplateCode from './OpaqueOutputTemplateCode'
import './LocalMediaProfileCard.css'

export type LocalMediaProfileCardProps = {
  profile: LocalMediaProfileRead
  selected?: boolean
  onClick?: () => void
}

export default function LocalMediaProfileCard({ profile, selected = false, onClick }: LocalMediaProfileCardProps) {
  return (
    <button
      type="button"
      role="listitem"
      className={selected ? 'card local-media-profile-card selected' : 'card local-media-profile-card'}
      aria-pressed={selected}
      onClick={onClick}
    >
      <div className="card-title">{profile.name}</div>
      {/* The same path as in the Local Media Profiles table. */}
      <OpaqueOutputTemplateCode
        source={profile.outputTemplate}
        sourceMode="compact"
        renderMode="simplified-path"
        label={`Output path template for ${profile.name}`}
        className="local-media-profile-card__path"
      />
      <div className="card-meta">
        <span>{LocalMediaProfileTypeReg.getLabelLoose(profile.type)}</span>
        <span>{PreferredFormatReg.getLabelLoose(profile.preferredFormat)}</span>
      </div>
    </button>
  )
}
