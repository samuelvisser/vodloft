import {useEffect, useMemo, useRef} from "react";
import {useSearchParams} from "react-router-dom";
import CollectionPreviewCard from "./CollectionPreviewCard";
import {useListedCollectionDetails, useResolvedLink} from "../../lib/queries";
import {SourceFeature, sourceHas} from "../../types/schemas/source";
import ReadMore from "../../utils/ReadMore";
import {collectionWords, creatorNamesFor} from "../../lib/collectionWords";
import {can} from "../../lib/access";
import CreatorSwitch, {type CreatorChoice} from "./CreatorSwitch";
import {listedCollectionDefaults} from "./collectionDefaults";
import {Controller, SubmitHandler, useForm} from "react-hook-form";
import {zodResolver} from "@hookform/resolvers/zod";
import {
    CollectionCreateFormSchema,
    CollectionCreatePayloadSchema,
    type CollectionCreateFormIn, CollectionCreatePayloadOut, CollectionCreatePayloadIn,
} from "../../types/schemas/collection";
import {CollectionTypeReg, episodeIdentifierRegFor, musicIdentificationAdvice} from "../../types/collection";
import Select from '../../components/common/Select'
import {SeasonDetachedOut} from "../../types/schemas/season";
import {createSelectRegistry} from "../../utils/selectRegistry";

type Props = {
    value: Partial<CollectionCreatePayloadIn>
    onChange: (v: Partial<CollectionCreatePayloadIn>) => void;
    onSubmit: (v: CollectionCreatePayloadOut) => void;
    onSeasonsSubmit: (seasons: SeasonDetachedOut[]) => void;
    onContinue: () => void;
    onCancel: () => void;
    /** Whether the collection is added to a creator once it is in the Library: only a channel can be. */
    creator: CreatorChoice;
    onCreatorChange: (choice: CreatorChoice) => void;
};

export default function ChooseCollectionStep({value, onChange, onSubmit: onSubmitParent, onSeasonsSubmit, onContinue, onCancel, creator, onCreatorChange}: Props) {
    // --- Form: only user-editable fields are in this schema
    const form = useForm<CollectionCreateFormIn>({
        resolver: zodResolver(CollectionCreateFormSchema),
        mode: "onBlur",
        defaultValues: value,
    });

    const {
        register,
        setValue,
        setError,
        watch,
        control,
        handleSubmit,
        formState: {isSubmitting, errors},
    } = form;

    // --- Subscribe to ALL form changes
    useEffect(() => {
        const subscription = watch((values: CollectionCreateFormIn) => {
            onChange(values); // push up on every change
        });
        return () => subscription.unsubscribe();
    }, [watch, onChange]);

    // --- Watch the URL and extract the slug when valid
    const watchedUrl = watch("url");
    // Add media opens the page with the link it looked up (?url=...); without one, the link is typed here.
    const [params] = useSearchParams();
    const linkGiven = !!params.get("url")?.trim();
    const urlParsed = useMemo(() => CollectionCreateFormSchema.shape.url.safeParse(watchedUrl ?? ""), [watchedUrl]);

    // --- The Source that recognises the link says what it points to, and describes the collection itself.
    const resolved = useResolvedLink(urlParsed.success ? urlParsed.data : undefined)
    const resolvedCollection = resolved.data?.kind === 'collection' ? resolved.data : undefined
    const listedSource = resolvedCollection && sourceHas(resolvedCollection.source, SourceFeature.COLLECTION_DETAILS)
        ? resolvedCollection.source
        : undefined
    const listed = useListedCollectionDetails(listedSource?.id, listedSource ? resolved.data?.url : undefined);
    // What a collection of the chosen type calls its seasons and episodes; a Music collection on a Site with sound
    // only, such as SoundCloud, holds tracks.
    const typeWords = collectionWords(watch("type"), listed.data?.audioOnly ? 'audio' : 'video')
    const lastListedUrlRef = useRef<string | undefined>(
        value.type && value.episodeIdentifier ? value.url : undefined,
    );
    useEffect(() => {
        if (!listed.data) return;
        setValue("membershipLevel", listed.data.membershipLevel, {shouldValidate: true});
        // Suggest the type the backend guessed, from the name or because it is music, and identification to match.
        if (lastListedUrlRef.current === listed.data.sharingUrl) return;
        lastListedUrlRef.current = listed.data.sharingUrl;
        const suggested = listedCollectionDefaults(listed.data);
        setValue("type", suggested.type, {shouldDirty: true});
        setValue("episodeIdentifier", suggested.episodeIdentifier, {shouldDirty: true});
    }, [listed.data, setValue]);

    // The membership levels the collection can list with, at a Source that has them.
    const membershipLevels = useMemo(() => {
        const levels = listed.data?.membershipLevels ?? []
        return createSelectRegistry('MembershipLevel', Object.fromEntries(
            levels.map(level => [level.key, {label: level.name, help: level.help}]),
        ), levels.map(level => level.key))
    }, [listed.data?.membershipLevels])

    // --- Submit handler
    const onSubmit: SubmitHandler<CollectionCreateFormIn> = (formOnly: CollectionCreateFormIn) => {
        if (!listed.data) {
            setError("url", {type: "validate", message: "Paste the link to a collection or channel"});
            return;
        }
        const details = listed.data;
        onSeasonsSubmit(details.seasons);
        onSubmitParent(CollectionCreatePayloadSchema.parse({
            ...formOnly,
            sourceKey: details.sourceKey,
            slug: details.slug,
            title: details.title,
            description: details.description ?? null,
            backgroundImagePath: null,
            logoImagePath: null,
            sharingUrl: details.sharingUrl,
            listType: details.listType,
            authorName: details.authorName,
            authorSlug: details.authorSlug,
            authorHeadshotPath: details.authorHeadshotPath ?? null,
            thumbnailLandscapePath: details.thumbnailLandscapePath ?? null,
            thumbnailPortraitPath: null,
            thumbnailSquarePath: null,
        }));
        onContinue();
    }

    const seasonsFromSource = !!listed.data?.seasons.length
    const episodeIdentifierField = (
        <div className="form-row">
            <label htmlFor="episode-identification">{typeWords.episode.Singular} identification</label>
            <Controller
                control={control}
                name="episodeIdentifier"
                render={({field}) => (
                    <Select
                        inputId="episode-identification"
                        options={episodeIdentifierRegFor(watch("type")).options}
                        value={episodeIdentifierRegFor(watch("type")).options.find(o => o.value === field.value) ?? null}
                        onChange={(opt) => field.onChange(opt?.value ?? "")}
                        onBlur={field.onBlur}
                        aria-invalid={!!errors.episodeIdentifier}
                        aria-describedby={errors.episodeIdentifier ? 'episode-identification-errors' : 'episode-identification-help'}
                        isClearable
                    />
                )}
            />
            {errors.episodeIdentifier && (
                <div id="episode-identification-errors" className="error" role="alert" aria-live="polite">
                    {errors.episodeIdentifier.message as string}
                </div>
            )}
            {musicIdentificationAdvice(watch("type"), watch("episodeIdentifier")) && (
                <div className="help form-advice" role="status">{musicIdentificationAdvice(watch("type"), watch("episodeIdentifier"))}</div>
            )}
            <div className="help" id="episode-identification-help">
                <ReadMore summary={<span>How are {typeWords.episode.plural} in this collection identified?</span>}>
                    <p>Determines how the collection's {typeWords.episode.plural} are grouped in the UI, and how they are indexed.</p>
                    <p><b>Numbered</b> {typeWords.episode.plural} are identified by {typeWords.episode.a} number. VODLoft will know
                        when {typeWords.episode.a} is part of another (e.g. a clip) and label it as such.</p>
                    <p><b>Date-based</b> {typeWords.episode.plural} are identified simply by their publish date.</p>
                    <p><b>{episodeIdentifierRegFor(watch("type")).getLabel('seasonal')}</b> {typeWords.episode.plural} are identified
                        by {typeWords.season.a} number and {typeWords.episode.a} number, like "S01E01".
                        Auxiliary content like trailers will be identified separately.</p>
                    {listed.data && (seasonsFromSource
                        ? <p>{resolved.data?.source.name} has its own seasons, which VODLoft keeps, and a Seasonal collection keeps its {typeWords.episode.singular} numbers too.</p>
                        : listed.data.seasonsPlans[watch("type") ?? ""] && <p>{listed.data.seasonsPlans[watch("type") ?? ""]}</p>)}
                    {!listed.data && <p>VODLoft suggests one from the collection itself. If you're unsure, select "Numbered".</p>}
                </ReadMore>
            </div>
        </div>
    )

    // A channel or a list, on a Site with creators, can be added to one of them.
    const siteCreatorNames = resolved.data?.creatorNames ?? null
    const creatorSwitch = siteCreatorNames && can('library', 'manage') ? (
        <CreatorSwitch creatorNames={creatorNamesFor(watch("type"), siteCreatorNames)} value={creator} onChange={onCreatorChange}/>
    ) : null

    // --- Render
    return (
        <form className="form" onSubmit={handleSubmit(onSubmit)} noValidate>
            {errors.root && (
                <div className="form-error-card" role="alert" aria-live="polite">
                    {String(errors.root.message)}
                </div>
            )}
            {linkGiven ? (
                <>
                    <input type="hidden" {...register("url")}/>
                    {errors.url && (
                        <div className="form-error-card" role="alert" aria-live="polite">{errors.url.message as string}</div>
                    )}
                </>
            ) : (
                <div className="form-row">
                    <label htmlFor="collection-url">Collection link</label>
                    <input
                        id="collection-url"
                        className="input"
                        type="url"
                        inputMode="url"
                        placeholder="https://…"
                        {...register("url")}
                        aria-invalid={!!errors.url}
                        aria-describedby={errors.url ? "collection-url-validate" : undefined}
                    />
                    {errors.url && (
                        <div id="collection-url-validate" className="error" role="alert" aria-live="polite">
                            {errors.url.message as string}
                        </div>
                    )}
                    <div id="url-help" className="help">
                        The link to the collection's own page, such as a Daily Wire show, a YouTube channel or a playlist.
                        To add something else, use Add media.
                    </div>
                </div>
            )}

            {/* The collection, as its Source describes it */}
            {urlParsed.success && (
                <>
                    <div className="form-row" aria-live="polite">
                        {resolved.isPending || listed.isFetching ? (
                            <div className="dw-card" aria-busy="true">
                                <div className="dw-card-body">
                                    <div className="dw-card-title">Checking collection…</div>
                                    <div className="dw-card-desc">Looking up this link</div>
                                </div>
                            </div>
                        ) : resolved.isError || listed.isError ? (
                            <div className="form-error-card" role="alert">
                                {(resolved.error ?? listed.error)?.message}
                            </div>
                        ) : listed.data ? (
                            <CollectionPreviewCard
                                title={listed.data.title}
                                authorName={listed.data.authorName}
                                description={listed.data.description}
                                imageUrl={listed.data.thumbnailLandscapePath}
                            />
                        ) : (
                            <div className="form-error-card" role="alert">
                                {resolved.data?.kind === 'collection'
                                    ? `VODLoft cannot add collections from ${resolved.data.source.name} yet.`
                                    : 'This link is not a collection. Paste the link to a collection, channel or playlist, or add it from Add media.'}
                            </div>
                        )}
                    </div>
                    {listed.data && listed.data.membershipLevels.length > 0 && (
                        <div className="form-row">
                            <label htmlFor="membership-level">Membership level</label>
                            <Controller
                                control={control}
                                name="membershipLevel"
                                render={({field}) => (
                                    <Select
                                        inputId="membership-level"
                                        options={membershipLevels.options}
                                        value={membershipLevels.options.find(o => o.value === field.value) ?? null}
                                        onChange={(opt) => field.onChange(opt?.value ?? "")}
                                        onBlur={field.onBlur}
                                        aria-invalid={!!errors.membershipLevel}
                                        aria-describedby={errors.membershipLevel ? 'membership-level-errors' : 'membership-level-help'}
                                    />
                                )}
                            />
                            {errors.membershipLevel && (
                                <div id="membership-level-errors" className="error" role="alert" aria-live="polite">
                                    {errors.membershipLevel.message as string}
                                </div>
                            )}
                            <div className="help" id="membership-level-help">
                                <ReadMore summary={<span>The membership level VODLoft indexes this collection with.</span>}>
                                    <p>VODLoft only indexes {typeWords.episode.plural} up to this membership level. It starts at
                                        the level of the account you are signed in with at {resolved.data?.source.name}.
                                        If your membership expires, gives access to a lower level than set here, or VODLoft
                                        loses access to your account, indexing is paused.</p>
                                    <p>With <strong>{membershipLevels.getLabelLoose('HIGHEST_ALLOWED')}</strong>, VODLoft indexes
                                        with whatever level your account has at the time. If that changes, {typeWords.episode.plural} of
                                        different membership levels can end up mixed in one collection.</p>
                                </ReadMore>
                            </div>
                        </div>
                    )}
                    {listed.data && (
                        <div className="form-row">
                            <label htmlFor="collection-type">Collection type</label>
                            <Controller
                                control={control}
                                name="type"
                                render={({field}) => (
                                    <Select
                                        inputId="collection-type"
                                        options={CollectionTypeReg.options}
                                        value={CollectionTypeReg.options.find(o => o.value === field.value) ?? null}
                                        onChange={(opt) => field.onChange(opt?.value ?? "")}
                                        onBlur={field.onBlur}
                                        aria-invalid={!!errors.type}
                                        aria-describedby={errors.type ? 'collection-type-errors' : 'collection-type-help'}
                                        isClearable
                                    />
                                )}
                            />
                            {errors.type && (
                                <div id="collection-type-errors" className="error" role="alert" aria-live="polite">
                                    {errors.type.message as string}
                                </div>
                            )}
                            <div className="help" id="collection-type-help">
                                {listed.data?.musicReason && watch("type") === CollectionTypeReg.Enum.music && (
                                    <p>{listed.data.musicReason}, so VODLoft took it for music. Pick another type if it isn't.</p>
                                )}
                                <ReadMore summary={<span>Why do I need to choose this?</span>}>
                                    <p><b>Podcast</b> collections download and stream episodes from <i>newest</i> to <i>oldest</i>,
                                        which suits most channels.</p>
                                    <p><b>Series</b> collections download and stream episodes from <i>oldest</i> to <i>newest</i>,
                                        which suits a playlist you watch in order.</p>
                                </ReadMore>
                            </div>
                        </div>
                    )}
                    {listed.data && episodeIdentifierField}
                    {listed.data && creatorSwitch}
                </>
            )}

            <div className="actions">
                <input type="submit" className="btn btn-primary" value="Continue" disabled={isSubmitting}/>
                <button type="button" className="btn" onClick={onCancel}>
                    Cancel
                </button>
            </div>
        </form>
    );
}
