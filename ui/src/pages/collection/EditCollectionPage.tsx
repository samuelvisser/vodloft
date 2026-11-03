import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import CollectionForm, { CollectionFormValue, defaultCollectionFormValue } from '../../components/CollectionForm'
import CustomMetadataEditor from '../../components/CustomMetadataEditor/CustomMetadataEditor'
import { useQueryClient } from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useCollection} from '../../lib/queries'
import SimpleSelect from '../../components/common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import {faIcon} from '../../icons/faIcon'
import OptionsEditor from '../../components/common/OptionsEditor/OptionsEditor'
import ReadMore from '../../utils/ReadMore'
import {hasSourceFeature, SourceFeature} from '../../types/schemas/source'

type RouteParams = { id?: string }

type FormState = CollectionFormValue & {
  url: string
  localMediaProfileId: string
  ytdlpOptions: string
}

export default function EditCollectionPage() {
  const { id } = useParams<RouteParams>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [metadataOpen, setMetadataOpen] = useState(false)
  const [urlCopied, setUrlCopied] = useState(false)
  const [optionsError, setOptionsError] = useState<string | null>(null)
  const {data: collection} = useCollection(id)
  const initializedCollectionId = useRef<string | undefined>(undefined)

  const [form, setForm] = useState<FormState>(() => ({
    url: id ? `https://www.dailywire.com/show/${id}` : '',
    localMediaProfileId: 'p1',
    ytdlpOptions: '',
    ...defaultCollectionFormValue,
  }))

  type LocalMediaProfileName = { id: string; name: string }
  const [profiles, setProfiles] = useState<LocalMediaProfileName[] | null>(null)
  const [profilesError, setProfilesError] = useState<string | null>(null)
  const profileReg = useMemo(() => {
    const spec: Record<string, {label: string}> = {}
    const values: string[] = []
    for (const profile of profiles ?? []) {
      spec[profile.id] = {label: profile.name}
      values.push(profile.id)
    }
    return createSelectRegistry('EditCollectionLocalMediaProfile', spec, values)
  }, [profiles])

  useEffect(() => {
    if (!id || !collection || collection.slug !== id || initializedCollectionId.current === id) return

    initializedCollectionId.current = id
    setForm((prev) => ({
      ...prev,
      url: collection.sharingUrl,
      name: collection.title,
      author: collection.authorName,
      ytdlpOptions: collection.ytdlpOptions ?? '',
    }))
  }, [id, collection])

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${(window as any).appConfig.API_URL}/collection-local-media-profiles`, { signal: controller.signal, credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const data = await r.json()
        const items = (data as any[]).map((p) => ({ id: p.slug, name: p.name }))
        setProfiles(items)
        // Ensure selected value is valid
        setForm((prev) => {
          if (!prev.localMediaProfileId || !items.some((x) => x.id === prev.localMediaProfileId)) {
            return { ...prev, localMediaProfileId: items[0]?.id ?? '' }
          }
          return prev
        })
      })
      .catch((e: any) => {
        if (e.name !== 'AbortError') {
          console.error('Failed to load media profiles', e)
          setProfilesError('Failed to load media profiles')
          setProfiles([])
        }
      })
    return () => controller.abort()
  }, [])

  const usesYtdlp = hasSourceFeature(collection, SourceFeature.YTDLP_DOWNLOADS)

  const onCancel = () => navigate(`/collection/${id ?? ''}`)
  const onSave = async () => {
    if (!id || !collection) return
    const payload = {
      title: form.name,
      description: collection.description,
      sharingUrl: form.url,
      ...(collection.membershipLevel !== undefined ? {membershipLevel: collection.membershipLevel} : {}),
      authorName: form.author,
      authorHeadshotPath: collection.authorHeadshotPath ?? null,
      backgroundImagePath: collection.backgroundImagePath ?? null,
      logoImagePath: collection.logoImagePath ?? null,
      thumbnailLandscapePath: collection.thumbnailLandscapePath ?? null,
      thumbnailPortraitPath: collection.thumbnailPortraitPath ?? null,
      thumbnailSquarePath: collection.thumbnailSquarePath ?? null,
      ...(usesYtdlp ? {ytdlpOptions: form.ytdlpOptions} : {}),
    }
    const r = await fetch(`${(window as any).appConfig.API_URL}/collections/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    })
    if (r.status === 422) {
      const body = await r.json().catch(() => null)
      const problem = (body?.detail ?? []).find((item: any) => Array.isArray(item?.loc) && item.loc.includes('ytdlpOptions'))
      if (problem) {
        setOptionsError(String(problem.msg).replace(/^Value error, /, ''))
        return
      }
    }
    if (!r.ok) {
      const msg = `Failed to save collection (HTTP ${r.status})`
      console.error(msg)
      alert(msg)
      return
    }
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['collection', id] }),
      qc.invalidateQueries({ queryKey: ['collections'] }),
      qc.invalidateQueries({ queryKey: ['collectionsView'] }),
    ])
    navigate(`/collection/${id ?? ''}`)
  }

  if (!id) {
    return (
      <section className="view" aria-labelledby="edit-collection-title">
        <div className="view-header">
          <h1 id="edit-collection-title">Edit collection</h1>
        </div>
        <p>Collection not found.</p>
        <div className="actions" style={{ marginTop: 12 }}>
          <button type="button" className="btn" onClick={() => navigate('/')}>Back</button>
        </div>
      </section>
    )
  }

  const onCopyUrl = async () => {
    if (!form.url) return
    try {
      await navigator.clipboard.writeText(form.url)
      setUrlCopied(true)
      setTimeout(() => setUrlCopied(false), 2000)
    } catch {
      // The URL stays visible in the field when clipboard access is unavailable.
    }
  }

  return (
    <section className="view" aria-labelledby="edit-collection-title">
      <div className="view-header">
        <h1 id="edit-collection-title">Edit collection</h1>
        {collection && (
          <button type="button" className="btn" onClick={() => setMetadataOpen(true)}>
            Metadata
          </button>
        )}
      </div>

      <form className="form" onSubmit={(e) => e.preventDefault()}>
        <div className="form-row">
          <label htmlFor="collection-url">Collection URL</label>
          <div className="rss-feed-url-group">
            <input
              id="collection-url"
              className="input rss-feed-url-input"
              type="url"
              inputMode="url"
              placeholder="https://…"
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
              disabled
            />
            <div className="rss-feed-url-actions">
              <button
                type="button"
                className="rss-feed-url-action"
                onClick={onCopyUrl}
                disabled={!form.url}
                aria-label={urlCopied ? 'Collection URL copied' : 'Copy collection URL'}
                title={urlCopied ? 'Copied!' : 'Copy collection URL'}
                aria-live="polite"
              >
                <FontAwesomeIcon
                  className="rss-feed-url-action-icon"
                  icon={faIcon('fass', urlCopied ? 'check' : 'copy') as any}
                  aria-hidden="true"
                />
                <span className="rss-feed-url-action-text">{urlCopied ? 'Copied!' : 'Copy'}</span>
              </button>
            </div>
          </div>
        </div>

        <div className="form-row">
          <label htmlFor="media-profile">Media Profile</label>
          <SimpleSelect
            inputId="media-profile"
            registry={profileReg}
            value={form.localMediaProfileId}
            onChange={(value) => setForm({ ...form, localMediaProfileId: value })}
            isDisabled
            placeholder={profiles === null ? 'Loading profiles...' : profilesError ?? 'No profiles found'}
          />
        </div>

        <CollectionForm
          value={form}
          onChange={(v: CollectionFormValue) => setForm((prev) => ({ ...prev, ...v }))}
        />

        {usesYtdlp && (
          <div className="form-row">
            <label htmlFor="collection-ytdlp-options">Your own yt-dlp options</label>
            <OptionsEditor
              id="collection-ytdlp-options"
              value={form.ytdlpOptions}
              onChange={(value) => {
                setOptionsError(null)
                setForm((prev) => ({ ...prev, ytdlpOptions: value }))
              }}
              invalid={!!optionsError}
              describedBy={optionsError ? 'collection-ytdlp-options-errors' : 'collection-ytdlp-options-help'}
            />
            {optionsError && (
              <div id="collection-ytdlp-options-errors" className="error" role="alert" aria-live="polite">{optionsError}</div>
            )}
            <div className="help" id="collection-ytdlp-options-help">
              <ReadMore summary="Exceptions for this Collection, on top of the yt-dlp Source’s options in Settings. Most Collections leave this empty.">
                <p>These lines come after the yt-dlp options in Settings, under Sources, so for an option set in both places this Collection’s wins.
                  Each line is checked with yt-dlp’s own parser, and the same options are blocked as in Settings.</p>
              </ReadMore>
            </div>
          </div>
        )}

        <div className="actions">
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={onSave} disabled={!collection}>Save changes</button>
        </div>
      </form>

      <CustomMetadataEditor
        open={metadataOpen}
        title="Collection metadata"
        scope="collection"
        metadata={collection?.customMetadata ?? {}}
        endpoint={`/collections/${encodeURIComponent(id)}/metadata`}
        invalidateQueryKeys={[
          ['collection', id],
          ['collections'],
          ['collectionsView'],
        ]}
        onDismiss={() => setMetadataOpen(false)}
      />
    </section>
  )
}
