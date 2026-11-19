import { Link } from 'react-router-dom'

export type CollectionFormValue = {
  name: string
  author: string
  downloadMedia: boolean
  downloadDelayMinutes: string
  redownloadAfterMinutes: string
  downloadDays: string // keep string to allow empty input
  deleteOlder: boolean
  titleFilter: string
}

export const defaultCollectionFormValue: CollectionFormValue = {
  name: '',
  author: '',
  downloadMedia: true,
  downloadDelayMinutes: '90',
  redownloadAfterMinutes: '180',
  downloadDays: '180',
  deleteOlder: true,
  titleFilter: '',
}

type Props = {
  value: CollectionFormValue
  onChange: (value: CollectionFormValue) => void
  /** The creator the collection belongs to, whose name is its author. */
  creator?: { slug: string, title: string } | null
}

export default function CollectionForm({ value, onChange, creator }: Props) {

  return (
    <>
      <div className="form-row">
        <label htmlFor="collection-name">Collection name</label>
        <input
          id="collection-name"
          className="input"
          type="text"
          placeholder="The Ben Shapiro Show"
          value={value.name}
          onChange={(e) => onChange({ ...value, name: e.target.value })}
        />
      </div>

      <div className="form-row">
        <label htmlFor="collection-author">Author</label>
        <input
          id="collection-author"
          className="input"
          type="text"
          placeholder="Ben Shapiro"
          value={creator ? creator.title : value.author}
          onChange={(e) => onChange({ ...value, author: e.target.value })}
          disabled={!!creator}
          aria-describedby={creator ? 'collection-author-help' : undefined}
        />
        {creator && (
          <div className="help" id="collection-author-help">
            The name of its creator, {creator.title}. Change it on the{' '}
            <Link to={`/edit-creator/${creator.slug}`}>creator's Edit page</Link>.
          </div>
        )}
      </div>


    </>
  )
}
