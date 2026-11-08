import AddCollectionPageImpl from '../../components/AddCollectionPage/AddCollectionPage'
import {useSearchParams} from 'react-router-dom'

export type AddCollectionPageProps = {
  onCancel: () => void
  onCreated: (path: string) => void
}

export default function AddCollectionPage({ onCancel, onCreated }: AddCollectionPageProps) {
  const [params] = useSearchParams()
  const initialUrl = params.get('url') || undefined
  return (
    <section className="view" aria-labelledby="add-collection-title">
      <div className="view-header">
        <h1 id="add-collection-title">Add collection</h1>
      </div>
      <AddCollectionPageImpl onCancel={onCancel} onCreated={onCreated} initialUrl={initialUrl} />
    </section>
  )
}
