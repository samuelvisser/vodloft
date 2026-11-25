import { useEffect, useRef, useState } from 'react'
import {Link, useNavigate, useParams, useSearchParams} from 'react-router-dom'
import CollectionForm, { CollectionFormValue, defaultCollectionFormValue } from '../../components/CollectionForm'
import CustomMetadataEditor from '../../components/CustomMetadataEditor/CustomMetadataEditor'
import { useQueryClient } from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useCollection, useCollectionSeasons} from '../../lib/queries'
import SimpleSelect from '../../components/common/SimpleSelect'
import {faIcon} from '../../icons/faIcon'
import OptionsEditor from '../../components/common/OptionsEditor/OptionsEditor'
import ReadMore from '../../utils/ReadMore'
import {hasSourceFeature, SourceFeature} from '../../types/schemas/source'
import CronEditor from '../../components/Settings/CronEditor'
import {useQuery} from '@tanstack/react-query'
import {toast} from '../../lib/toast'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {removeEpisodePreviewFromStorage} from '../../lib/cache'
import {forgetDeletedCollection} from '../../lib/deletedCollection'
import {episodeQueryKeys} from '../../lib/collectionQueryOptions'
import {CheckFrequencyReg, type CheckFrequency, CollectionTypeReg, CollectionTypeValue, CookiesModeReg, type CookiesMode, SplitChaptersReg, episodeIdentifierRegFor, musicIdentificationAdvice, EpisodeIdentifierValue, EpisodeOrderReg, EpisodeOrderValue} from '../../types/collection'
import ChangeIdentificationDialog from '../../components/ChangeIdentificationDialog/ChangeIdentificationDialog'
import ProgressSelect from '../../components/common/ProgressSelect'
import {frontendOperationDefinitions} from '../../lib/operationDefinitions'
import {apiUrl} from '../../lib/api'
import SeasonsDialog from '../../components/CollectionSeasons/SeasonsDialog'
import ReconcileDialog from '../../components/ReconcileDialog/ReconcileDialog'
import PageHeader, {PageHeaderAction} from '../../components/common/PageHeader'
import {collectionWords, wordsFor} from '../../lib/collectionWords'
import Breadcrumb from '../../components/common/Breadcrumb/Breadcrumb'


type RouteParams = { id?: string }

type FormState = CollectionFormValue & {
  url: string
  ytdlpOptions: string
  checkFrequency: CheckFrequency
  checkCron: string
  cookiesMode: CookiesMode
  splitChapters: boolean
  episodeOrder: EpisodeOrderValue
  genre: string
  contentRating: string
  type: CollectionTypeValue
}

export default function EditCollectionPage() {
  const { id } = useParams<RouteParams>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [metadataOpen, setMetadataOpen] = useState(false)
  // The Move dialog, for the downloaded episodes a save of the seasons left in another season.
  const [moving, setMoving] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()
  // A message about new playlists opens the Seasons dialog straight away.
  const seasonsOpen = searchParams.get('seasons') === '1'
  const setSeasonsOpen = (next: boolean) => setSearchParams((params) => {
    const changed = new URLSearchParams(params)
    if (next) changed.set('seasons', '1')
    else changed.delete('seasons')
    return changed
  }, {replace: true})
  const [urlCopied, setUrlCopied] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const [optionsError, setOptionsError] = useState<string | null>(null)
  const {data: collection} = useCollection(id)
  // A Music collection that is one album, such as one made from an album, has no albums to group its tracks by.
  const {data: seasons} = useCollectionSeasons(id)
  const oneAlbum = seasons?.length === 1
  const initializedCollectionId = useRef<string | undefined>(undefined)

  const [form, setForm] = useState<FormState>(() => ({
    url: '',
    ytdlpOptions: '',
    checkFrequency: 'default',
    checkCron: '0 */6 * * *',
    cookiesMode: 'automatic',
    splitChapters: false,
    episodeOrder: 'newest_first',
    genre: '',
    contentRating: '',
    type: 'series',
    ...defaultCollectionFormValue,
  }))
  // What the collection calls its seasons and episodes, by the type chosen here.
  const words = wordsFor({type: form.type, site: collection?.site})
  // What the parts of a video split by its chapters are: sound in a Music collection, such as an album of tracks.
  const parts = collectionWords(form.type, 'audio')
  const musicParts = collectionWords('music', 'audio')

  useEffect(() => {
    if (!id || !collection || collection.slug !== id || initializedCollectionId.current === id) return

    initializedCollectionId.current = id
    setForm((prev) => ({
      ...prev,
      url: collection.sharingUrl ?? '',
      name: collection.title,
      author: collection.authorName,
      ytdlpOptions: collection.ytdlpOptions ?? '',
      checkFrequency: collection.checkFrequency,
      checkCron: collection.checkCron || prev.checkCron,
      cookiesMode: collection.cookiesMode,
      splitChapters: collection.splitChapters,
      episodeOrder: collection.episodeOrder,
      genre: collection.genre ?? '',
      contentRating: collection.contentRating ?? '',
      type: CollectionTypeReg.normalize(collection.type) ?? prev.type,
    }))
  }, [id, collection])

  const [identificationTarget, setIdentificationTarget] = useState<EpisodeIdentifierValue | null>(null)

  const usesYtdlp = hasSourceFeature(collection, SourceFeature.YTDLP_OPTIONS)
  const optionalCookies = hasSourceFeature(collection, SourceFeature.OPTIONAL_COOKIES)
  const chapters = hasSourceFeature(collection, SourceFeature.CHAPTERS)
  const [cronError, setCronError] = useState<string | null>(null)
  const [typeError, setTypeError] = useState<string | null>(null)
  const [urlError, setUrlError] = useState<string | null>(null)
  // A collection that holds only what its links have may go without a link of its own, or change it.
  const linkOptional = collection?.outsideVideos === 'only'
  const {data: suggestion} = useQuery({
    queryKey: ['collection', id, 'checkSuggestion'],
    enabled: !!id,
    queryFn: async ({signal}) => {
      const r = await fetch(`${apiUrl()}/collections/${id}/check-suggestion`, {signal, credentials: 'include'})
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
      sharingUrl: form.url.trim() || null,
      ...(collection.membershipLevel !== undefined ? {membershipLevel: collection.membershipLevel} : {}),
      authorName: form.author,
      authorHeadshotPath: collection.authorHeadshotPath ?? null,
      backgroundImagePath: collection.backgroundImagePath ?? null,
      logoImagePath: collection.logoImagePath ?? null,
      thumbnailLandscapePath: collection.thumbnailLandscapePath ?? null,
      thumbnailPortraitPath: collection.thumbnailPortraitPath ?? null,
      thumbnailSquarePath: collection.thumbnailSquarePath ?? null,
      ...(usesYtdlp ? {ytdlpOptions: form.ytdlpOptions} : {}),
      type: form.type,
      episodeOrder: form.episodeOrder,
      genre: form.genre,
      contentRating: form.contentRating,
      checkFrequency: form.checkFrequency,
      ...(form.checkFrequency === 'own' ? {checkCron: form.checkCron} : {}),
      ...(optionalCookies ? {cookiesMode: form.cookiesMode} : {}),
      ...(chapters ? {splitChapters: form.splitChapters} : {}),
    }
    const r = await fetch(`${apiUrl()}/collections/${id}`, {
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
      const urlProblem = problemAt('sharingUrl', 'sharing_url')
      if (urlProblem) {
        setUrlError(String(urlProblem.msg).replace(/^Value error, /, ''))
        return
      }
      const typeProblem = problemAt('type')
      if (typeProblem) {
        setTypeError(String(typeProblem.msg).replace(/^Value error, /, ''))
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
    if (form.episodeOrder !== collection.episodeOrder) {
      // The stored preview and loaded pages are in the old order.
      removeEpisodePreviewFromStorage(id)
      qc.removeQueries({queryKey: episodeQueryKeys.forCollection(id)})
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
    const url = `${apiUrl()}/collections/${id}`
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
    setDeleteConfirm(false)
    await forgetDeletedCollection(qc, id)
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
      {collection && (
        <Breadcrumb className="page-breadcrumb" items={[
          {label: 'Library', to: '/library'},
          // A creator's collection often has the creator's name, so it says which of the two it is.
          {label: collection.creatorSlug ? `Collection ${collection.title}` : collection.title, to: `/collection/${collection.slug}`},
        ]}/>
      )}
      <PageHeader
        title="Edit collection" titleId="edit-collection-title"
        actions={collection && (
          <>
            <PageHeaderAction icon={faIcon('fass', 'layer-group')} label={words.season.Plural} variant="secondary" caption onClick={() => setSeasonsOpen(true)}/>
            <PageHeaderAction icon={faIcon('fass', 'list')} label="Metadata" variant="secondary" caption onClick={() => setMetadataOpen(true)}/>
          </>
        )}
      />

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
              onChange={(e) => { setForm({ ...form, url: e.target.value }); setUrlError(null) }}
              disabled={!linkOptional}
              aria-invalid={urlError ? true : undefined}
              aria-describedby={linkOptional ? 'collection-url-help' : undefined}
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
          {urlError && <div className="error" role="alert">{urlError}</div>}
          {linkOptional && (
            <div className="help" id="collection-url-help">
              {collection?.kind === 'custom'
                ? 'Optional. A link of its own turns this custom collection into a channel or a list collection, by what the link is.'
                : `Optional. This collection holds only what its ${words.season.plural} have. A channel link here offers that channel's playlists in the ${words.season.Plural} window and finds new ones.`}
            </div>
          )}
        </div>

        <CollectionForm
          value={form}
          onChange={(v: CollectionFormValue) => setForm((prev) => ({ ...prev, ...v }))}
          creator={collection?.creatorSlug && collection.creatorTitle && collection.creatorNames ? {
            slug: collection.creatorSlug,
            title: collection.creatorTitle,
            word: collection.creatorNames.singular,
          } : null}
        />

        <div className="form-row">
          <label htmlFor="collection-genre">Genre</label>
          <input
            id="collection-genre"
            className="input"
            type="text"
            placeholder="Documentaries"
            value={form.genre}
            onChange={(e) => setForm((prev) => ({...prev, genre: e.target.value}))}
            aria-describedby="collection-genre-help"
          />
          <div className="help" id="collection-genre-help">
            Written into the NFO files that a Local Media Profile saves, so Jellyfin, Emby and Kodi show it.
          </div>
        </div>

        <div className="form-row">
          <label htmlFor="collection-content-rating">Content rating</label>
          <input
            id="collection-content-rating"
            className="input"
            type="text"
            placeholder="TV-14"
            value={form.contentRating}
            onChange={(e) => setForm((prev) => ({...prev, contentRating: e.target.value}))}
            aria-describedby="collection-content-rating-help"
          />
          <div className="help" id="collection-content-rating-help">
            The rating media servers show for the show and its {words.episode.plural}, such as TV-14 or TV-Y.
          </div>
        </div>

        <div className="form-row">
          <label htmlFor="collection-type">Collection type</label>
          <SimpleSelect
            inputId="collection-type"
            registry={CollectionTypeReg}
            value={form.type}
            onChange={(value) => {
              setTypeError(null)
              setForm((prev) => ({...prev, type: value as CollectionTypeValue}))
            }}
            aria-invalid={!!typeError}
            aria-describedby={typeError ? 'collection-type-error' : 'collection-type-help'}
          />
          {typeError && <div id="collection-type-error" className="error" role="alert">{typeError}</div>}
          <div className="help" id="collection-type-help">
            {CollectionTypeReg.getHelp(form.type) ?? ''} The Local Media Profiles offered for this collection depend on
            its type: a Music collection takes profiles available for Music.
          </div>
        </div>

        <div className="form-row">
          <label htmlFor="collection-episode-identification">{words.episode.Singular} identification</label>
          <ProgressSelect
            inputId="collection-episode-identification"
            registry={episodeIdentifierRegFor(form.type)}
            value={collection?.episodeIdentifier ?? null}
            isDisabled={!collection}
            definition={frontendOperationDefinitions['collection.change_identification']}
            resourceId={collection?.id}
            targetValueKey="episode_identifier"
            activeLabel={`Renumbering ${words.episode.plural}`}
            busyReason={`VODLoft is still numbering the ${words.episode.plural} of ${collection?.title ?? 'this collection'} again and renaming their files. You can change the identification again once that is done.`}
            onChange={(value) => {
              if (collection && value !== collection.episodeIdentifier) {
                setIdentificationTarget(value as EpisodeIdentifierValue)
              }
            }}
            aria-describedby="collection-episode-identification-help"
          />
          <div className="help" id="collection-episode-identification-help">
            How VODLoft numbers the {words.episode.plural}. Changing it numbers every {words.episode.singular} again, renames the files
            that are named by their numbers and rewrites their metadata.
          </div>
          {musicIdentificationAdvice(form.type, collection?.episodeIdentifier, oneAlbum) && (
            <div className="help form-advice" role="status">{musicIdentificationAdvice(form.type, collection?.episodeIdentifier, oneAlbum)}</div>
          )}
        </div>

        <div className="form-row">
          <label htmlFor="collection-episode-order">{words.episode.Singular} order</label>
          <SimpleSelect
            inputId="collection-episode-order"
            registry={EpisodeOrderReg}
            value={form.episodeOrder}
            onChange={(value) => setForm((prev) => ({...prev, episodeOrder: value as EpisodeOrderValue}))}
          />
          <div className="help">
            {collection?.episodeIdentifier === 'seasonal'
              ? `The order of the ${words.episode.plural} within each ${words.season.singular}`
              : `The order of the ${words.episode.plural}`}
            {' '}on the Collection page and in podcast apps that follow its RSS feeds.
            By default a seasonal Collection starts each {words.season.singular} at its first {words.episode.singular}, and any other Collection lists its newest {words.episode.singular} first.
          </div>
        </div>

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
          <label htmlFor="collection-check-frequency">Look for new {words.episode.plural}</label>
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

        {chapters && (
          <div className="form-row">
            <label htmlFor="collection-split-chapters">Videos with chapters</label>
            <SimpleSelect
              inputId="collection-split-chapters"
              registry={SplitChaptersReg}
              value={form.splitChapters ? 'split' : 'whole'}
              onChange={(value) => setForm((prev) => ({...prev, splitChapters: value === 'split'}))}
            />
            <div className="help">
              <ReadMore summary={
                form.splitChapters
                  ? `Each new video with chapters becomes ${parts.season.a} of its own, named after the video, with ${parts.episode.a} per chapter.`
                  : `Each video is one ${words.episode.singular}, chapters and all.`
              }>
                <p>Splitting suits full albums uploaded as one video: in a Music Collection each video becomes {musicParts.season.a} and
                  each chapter {musicParts.episode.a}. Each part downloads only its own stretch of the video and has its own file, so a
                  podcast app or music player plays it like any other {parts.episode.singular}. A feed can't stream a part straight from
                  the site, because the site only has the whole video.</p>
                <p>This only changes videos found from now on. Videos already in the Collection stay as they are.</p>
              </ReadMore>
            </div>
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
                <p>The cookies file is added per site in Settings, under Sources › Authentication. Signing in for every download can get an account
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

      {collection && (
        <ChangeIdentificationDialog
          open={identificationTarget !== null}
          collectionSlug={collection.slug}
          collectionTitle={collection.title}
          current={collection.episodeIdentifier as EpisodeIdentifierValue}
          collectionType={form.type}
          target={identificationTarget}
          episodeOrder={collection.episodeOrder}
          words={wordsFor(collection)}
          onDismiss={() => setIdentificationTarget(null)}
          onStarted={() => {
            setIdentificationTarget(null)
            navigate(`/collection/${collection.slug}`)
          }}
        />
      )}

      <SeasonsDialog
        open={seasonsOpen && !!collection}
        collectionSlug={id}
        collectionTitle={collection?.title ?? id}
        onDismiss={() => setSeasonsOpen(false)}
        onMovesWaiting={() => setMoving(true)}
        words={wordsFor(collection)}
      />

      <ReconcileDialog
        open={moving}
        path={`/collections/${encodeURIComponent(id)}`}
        what={`the ${wordsFor(collection).episode.plural} of ${collection?.title ?? id}`}
        onDismiss={() => setMoving(false)}
      />

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
