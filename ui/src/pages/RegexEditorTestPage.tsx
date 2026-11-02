import {useState} from 'react'
import {useSearchParams} from 'react-router-dom'

import PageSubtitle from '../components/common/PageSubtitle'
import SimpleSelect from '../components/common/SimpleSelect'
import RegexEditor, {type RegexValue} from '../components/RegexEditor/RegexEditor'
import {createSelectRegistry} from '../utils/selectRegistry'

const FieldReg = createSelectRegistry('RegexTestField', {
    title: {label: 'Titles'},
    description: {label: 'Descriptions'},
})

/**
 * The regex editor on its own, to try it before it is part of Which episodes.
 * Add ?collection=<id> to test on a Collection's indexed episodes.
 */
export default function RegexEditorTestPage() {
    const [params] = useSearchParams()
    const collection = Number(params.get('collection'))
    const [value, setValue] = useState<RegexValue>({pattern: '', ignoreCase: true})
    const [field, setField] = useState<'title' | 'description'>('title')

    return (
        <section className="view" aria-labelledby="regex-test-title">
            <div className="view-header">
                <h1 id="regex-test-title">Regex editor</h1>
                <PageSubtitle summary={<>The editor that Which episodes rules will use, on its own. Add <code>?collection=</code> and a Collection’s id to the address to test on its episodes.</>}/>
            </div>
            <div style={{display: 'grid', gap: 14, maxWidth: 900}}>
                <label style={{display: 'grid', gap: 6, maxWidth: 260, fontWeight: 700, fontSize: 12}}>
                    Test on
                    <SimpleSelect registry={FieldReg} value={field} onChange={(next) => setField(next as 'title' | 'description')}/>
                </label>
                <RegexEditor
                    id="regex-test"
                    value={value}
                    onChange={setValue}
                    field={field}
                    collectionId={Number.isInteger(collection) && collection > 0 ? collection : null}
                />
                <p className="regex-editor__muted">
                    Stored: <code>{JSON.stringify(value)}</code>
                </p>
            </div>
        </section>
    )
}
