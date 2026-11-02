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
}

export default function CollectionForm({ value, onChange }: Props) {

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
          value={value.author}
          onChange={(e) => onChange({ ...value, author: e.target.value })}
        />
      </div>


    </>
  )
}
