import {Link, useNavigate, useParams} from 'react-router-dom'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {useChannel} from '../../lib/queries'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import ChannelHeader from './ChannelHeader'
import './ChannelPages.css'

/** The places a collection lists, short enough for a card: "Videos, Live and 9 more". */
function listedSources(titles: string[]) {
    if (titles.length <= 3) return titles.slice(0, -1).join(', ') + ' and ' + titles[titles.length - 1]
    return `${titles.slice(0, 2).join(', ')} and ${titles.length - 2} more`
}

export default function ChannelPage() {
    const {slug} = useParams()
    const navigate = useNavigate()
    const {data: channel, error, isLoading} = useChannel(slug)

    if (isLoading) return <section className="view"><p>Loading…</p></section>
    if (error || !channel) {
        return (
            <section className="view">
                <div className="form-error-card" role="alert">{error?.message ?? 'This channel was not found'}</div>
            </section>
        )
    }

    const left = channel.sections.filter((section) => !section.collectionSlug && section.kind !== 'item')
    const addLink = (url: string) => navigate(`/add?url=${encodeURIComponent(url)}`)

    return (
        <section className="view channel-view" aria-labelledby="channel-title">
            <ChannelHeader
                title={channel.title} label={`${channel.site.name} ${channel.channelLabel}`} handle={channel.handle}
                avatarUrl={channel.avatarUrl} bannerUrl={channel.bannerUrl} facts={channel.facts}
                description={channel.description} url={channel.url} titleId="channel-title"
            />

            <div className="channel-section-group">
                <h2>In your library</h2>
                {channel.collections.length ? (
                    <div className="channel-collections">
                        {channel.collections.map((collection) => {
                            const image = toImageUrl(collection.thumbnailLandscapePath)
                            return (
                                <Link key={collection.slug} className="channel-collection" to={`/collection/${collection.slug}`}>
                                    {image
                                        ? <img src={image} alt="" loading="lazy"/>
                                        : <span className="channel-collection-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', 'tv')}/></span>}
                                    <b>{collection.title}</b>
                                    <span>
                                        {collection.episodeCount} {collection.episodeCount === 1 ? 'video' : 'videos'}
                                        {collection.links.length > 1 ? ` from ${listedSources(collection.links)}` : ''}
                                    </span>
                                </Link>
                            )
                        })}
                    </div>
                ) : (
                    <p>None of this {channel.channelLabel}'s collections are in your library any more.</p>
                )}
            </div>

            {left.length > 0 && (
                <div className="channel-section-group">
                    <h2>Not in your library</h2>
                    <div className="channel-section-list">
                        {left.map((section) => (
                            <div key={section.ref} className="channel-section-row">
                                {section.imageUrl
                                    ? <img className="channel-section-art" src={toImageUrl(section.imageUrl)} alt="" loading="lazy"/>
                                    : <span className="channel-section-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', section.kind === 'feed' ? 'rss' : 'list')}/></span>}
                                <div className="channel-section-copy">
                                    <b>{section.title}</b>
                                    <span>{[section.kindLabel, section.itemCount != null ? `${section.itemCount} videos` : null].filter(Boolean).join(' · ')}</span>
                                </div>
                                <button type="button" className="btn" onClick={() => addLink(section.url)}>Add as a collection</button>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </section>
    )
}
