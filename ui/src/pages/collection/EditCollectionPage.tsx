import { useEffect, useRef, useState } from 'react'
import {Link, useNavigate, useParams} from 'react-router-dom'
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
import CronEditor from '../../components/Settings/CronEditor'
import {useQuery} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {removeEpisodePreviewFromStorage, removeSeasonsFromStorage} from '../../lib/cache'
import {episodeQueryKeys} from '../../lib/collectionQueryOptions'

const CheckFrequencyReg = createSelectRegistry('CollectionCheckFrequency', {
  default: {label: 'Like other Collections'},
  less_often: {label: 'Less often'},
  own: {label: 'On its own schedule'},
})

const CookiesModeReg = createSelectRegistry('CollectionCookiesMode', {
  automatic: {label: 'Only when needed'},
  never: {label: 'Never'},
  always: {label: 'Always'},
})

type CheckFrequency = 'default' | 'less_often' | 'own'
type CookiesMode = 'automatic' | 'never' | 'always'

type RouteParams = { id?: string }

type FormState = CollectionFormValue & {
  url: string
  ytdlpOptions: string
  checkFrequency: CheckFrequency
  checkCron: string
  cookiesMode: CookiesMode
}

export default function EditCollectionPage() {
  const { id } = useParams<RouteParams>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [metadataOpen, setMetadataOpen] = useState(false)
  const [urlCopied, setUrlCopied] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const [optionsError, setOptionsError] = useState<string | null>(null)
  const {data: collection} = useCollection(id)
  const initializedCollectionId = useRef<string | undefined>(undefined)

  const [form, setForm] = useState<FormState>(() => ({
    url: id ? `https://www.dailywire.com/show/${id}` : '',
    ytdlpOptions: '',
    checkFrequency: 'default',
    checkCron: '0 */6 * * *',
    cookiesMode: 'automatic',
    ...defaultCollectionFormValue,
  }))

  useEffect(() => {
    if (!id || !collection || collection.slug !== id || initializedCollectionId.current === id) return

    initializedCollectionId.current = id
    setForm((prev) => ({
      ...prev,
      url: collection.sharingUrl,
      name: collection.title,
      author: collection.authorName,
      ytdlpOptions: collection.ytdlpOptions ?? '',
      checkFrequency: collection.checkFrequency,
      checkCron: collection.checkCron || prev.checkCron,
      cookiesMode: collection.cookiesMode,
    }))
  }, [id, collection])

  const usesYtdlp = hasSourceFeature(collection, SourceFeature.YTDLP_DOWNLOADS)
  const optionalCookies = hasSourceFeature(collection, SourceFeature.OPTIONAL_COOKIES)
  const [cronError, setCronError] = useState<string | null>(null)
  const {data: suggestion} = useQuery({
    queryKey: ['collection', id, 'checkSuggestion'],
    enabled: !!id,
    queryFn: async ({signal}) => {
      const r = await fetch(`${(window as any).appConfig.API_URL}/collections/${id}/check-suggestion`, {signal, credentials: 'include'})
      if (!r.ok) return null
      return ((await r.json()) as {suggestion: string | null}).suggestion
    },
  })
  const cookiesNeededUntil = collection?.cookiesNeededUntil ?? null
  const cookiesInUse = cookiesNeededUntil !== null && cookiesNeededUntil.getTime() > Date.now()

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
      checkFrequency: form.checkFrequency,
      ...(form.checkFrequency === 'own' ? {checkCron: form.checkCron} : {}),
      ...(optionalCookies ? {cookiesMode: form.cookiesMode} : {}),
    }
    const r = await fetch(`${(window as any).appConfig.API_URL}/collections/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    })
    if (r.status === 422) {
      const body = await r.json().catch(() => null)
      const problemAt = (...names: string[]) => (body?.detail ?? []).find(
        (item: any) => Array.isArray(item?.loc) && names.some((name) => item.loc.includes(name)),
      )
      const problem = problemAt('ytdlpOptions')
      if (problem) {
        setOptionsError(String(problem.msg).replace(/^Value error, /, ''))
        return
      }
      const cronProblem = problemAt('checkCron', 'check_cron')
      if (cronProblem) {
        setCronError(String(cronProblem.msg).replace(/^Value error, /, ''))
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

  const closeDeleteConfirm = () => setDeleteConfirm(false)
  const onConfirmDelete = async () => {
    if (!id) return
    const url = `${(window as any).appConfig.API_URL}/collections/${id}`
    const r = await fetch(url, { method: 'DELETE', credentials: 'include' })
    if (!r.ok) {
      let friendly = `Failed to delete collection (HTTP ${r.status})`
      try {
        const data = await r.json().catch(() => null as any)
        const details: any[] | undefined = data?.detail
        if (Array.isArray(details)) {
          const allErr = details.find((d) => Array.isArray(d?.loc) && d.loc[0] === 'body' && d.loc[1] === '__all__')
          if (allErr && typeof allErr.msg === 'string' && allErr.msg.trim()) friendly = allErr.msg
        }
      } catch (_) {
        // ignore JSON parse errors
      }
      console.error(friendly)
      toast.error(friendly)
      return
    }
    removeEpisodePreviewFromStorage(id)
    removeSeasonsFromStorage(id)
    setDeleteConfirm(false)

    await Promise.all([
      qc.cancelQueries({queryKey: ['collection', id]}),
      qc.cancelQueries({queryKey: ['seasons', id]}),
      qc.cancelQueries({queryKey: episodeQueryKeys.forCollection(id)}),
    ])
    qc.removeQueries({queryKey: ['collection', id]})
    qc.removeQueries({queryKey: ['seasons', id]})
    qc.removeQueries({queryKey: episodeQueryKeys.forCollection(id)})

    await Promise.all([
      qc.invalidateQueries({queryKey: ['collections']}),
      qc.invalidateQueries({queryKey: ['collectionsView']}),
    ])
    navigate('/library?type=collections')
  }


  if (!id) {
    return (
      <section className="view" aria-labelledby="edit-collection-title">
        <div className="view-header">
          <h1 id="edit-collection-title">Edit collection</h1>
        </div>
        <p>Collection not found.</p>
        <div className="actions" style={{ marginTop: 12 }}>
          <Link className="btn" to="/">Back</Link>
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

        <div className="form-row">
          <label htmlFor="collection-check-frequency">Look for new episodes</label>
          <SimpleSelect
            inputId="collection-check-frequency"
            registry={CheckFrequencyReg}
            value={form.checkFrequency}
            onChange={(value) => {
              setCronError(null)
              setForm((prev) => ({...prev, checkFrequency: value as CheckFrequency}))
            }}
          />
          <div className="help">
            {form.checkFrequency === 'less_often'
              ? 'At most every six hours, for a Collection that rarely posts. It still saves checks for everything else.'
              : form.checkFrequency === 'own'
                ? 'Only on the schedule below; the regular checks leave this Collection alone.'
                : 'On the schedule in Settings, like other Collections.'}
            {suggestion ? <> {suggestion}</> : null}
          </div>
        </div>

        {form.checkFrequency === 'own' && (
          <div className="form-row">
            <CronEditor
              id="collection-check-cron"
              label="Check schedule"
              value={form.checkCron}
              error={cronError ?? undefined}
              onChange={(value) => {
                setCronError(null)
                setForm((prev) => ({...prev, checkCron: value}))
              }}
            />
          </div>
        )}

        {optionalCookies && (
          <div className="form-row">
            <label htmlFor="collection-cookies-mode">Use the cookies file</label>
            <SimpleSelect
              inputId="collection-cookies-mode"
              registry={CookiesModeReg}
              value={form.cookiesMode}
              onChange={(value) => setForm((prev) => ({...prev, cookiesMode: value as CookiesMode}))}
            />
            <div className="help">
              <ReadMore summary={
                form.cookiesMode === 'automatic'
                  ? (cookiesInUse
                    ? `A download needed signing in, so downloads use the cookies file until ${cookiesNeededUntil!.toLocaleDateString()}.`
                    : 'Downloads run without the cookies file until one fails because the site wants you signed in.')
                  : form.cookiesMode === 'always'
                    ? 'Every download of this Collection signs in with the cookies file.'
                    : 'Downloads of this Collection never sign in, even when that makes them fail.'
              }>
                <p>The cookies file is added in Settings, under Sources. Signing in for every download can get an account
                  flagged, so by default VODLoft only uses it after a download failed because the site asked for a
                  sign-in, such as a bot check or a members-only video. It then keeps using it for a week, starting with
                  the retry.</p>
              </ReadMore>
            </div>
          </div>
        )}

        <div className="actions">
          <button
            type="button"
            className="btn btn-danger"
            style={{marginRight: 'auto'}}
            onClick={() => setDeleteConfirm(true)}
            disabled={!collection}
          >
            <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/>
            <span>Delete collection</span>
          </button>
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

      <ConfirmDialog
        open={deleteConfirm}
        title="Delete collection"
        onDismiss={closeDeleteConfirm}
        icon={faIcon('fass', 'trash')}
        iconTone="danger"
        confirmButton={{
          label: 'Delete',
          onClick: onConfirmDelete,
          className: 'btn btn-danger',
        }}
      >
        <p>Are you sure you want to delete "{collection?.title ?? id}"? This action cannot be undone.</p>
      </ConfirmDialog>
    </section>
  )
}
