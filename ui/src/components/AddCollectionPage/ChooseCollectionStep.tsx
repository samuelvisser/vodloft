import {useEffect, useMemo, useRef} from "react";
import DailywireShowCard from "./DailywireShowCard";
import CollectionPreviewCard from "./CollectionPreviewCard";
import {useDailywireShow, useDailywireUserInfo, useListedCollectionDetails, useResolvedLink} from "../../lib/queries";
import {DAILYWIRE_SOURCE_KEY, SourceFeature, sourceHas} from "../../types/schemas/source";
import ReadMore from "../../utils/ReadMore";
import {Controller, SubmitHandler, useForm} from "react-hook-form";
import {zodResolver} from "@hookform/resolvers/zod";
import {ZodSafeParseResult} from "zod";
import {
    CollectionCreateFormSchema,
    CollectionCreatePayloadSchema,
    type CollectionCreateFormIn, CollectionCreatePayloadOut, CollectionCreatePayloadIn,
} from "../../types/schemas/collection";
import {EpisodeIdentifierReg, EpisodeIdentifierValue, CollectionTypeReg, CollectionTypeValue} from "../../types/collection";
import Select from "react-select";
import {UseQueryResult} from "@tanstack/react-query";
import {SeasonDetachedOut, SeasonDetachedSchema} from "../../types/schemas/season";
import {DwMembershipLevelReg} from "../../types/dailywire_user_info";
import {DailywireShowRead, DailywireShowReadSchema} from "../../types/schemas/dailywire_show";
import {DailywireSeasonRead} from "../../types/schemas/dailywire_season";

type Props = {
    value: Partial<CollectionCreatePayloadIn>
    onChange: (v: Partial<CollectionCreatePayloadIn>) => void;
    onSubmit: (v: CollectionCreatePayloadOut) => void;
    onSeasonsSubmit: (seasons: SeasonDetachedOut[]) => void;
    onContinue: () => void;
    onCancel: () => void;
};

export default function ChooseCollectionStep({value, onChange, onSubmit: onSubmitParent, onSeasonsSubmit, onContinue, onCancel,}: Props) {
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
    const urlParsed = useMemo(() => CollectionCreateFormSchema.shape.url.safeParse(watchedUrl ?? ""), [watchedUrl]);
    const slugFromUrl: string | undefined = useMemo(() => {
        if (!urlParsed.success) return undefined;
        try {
            const parsedUrl = new URL(urlParsed.data ?? "");
            const path: string = parsedUrl.pathname;
            if (!path.startsWith("/show/")) return undefined;
            const s: string = path.slice("/show/".length).split("/")[0];
            return s || undefined;
        } catch {
            return undefined;
        }
    }, [urlParsed]);

    // --- A link that is not a Daily Wire show page goes to the Source that recognises it.
    // Sources that list their episodes describe the collection themselves.
    const resolved = useResolvedLink(urlParsed.success && !slugFromUrl ? urlParsed.data : undefined);
    const listedSource = resolved.data?.kind === 'collection' && sourceHas(resolved.data.source, SourceFeature.EPISODE_LISTS)
        ? resolved.data.source
        : undefined;
    const listed = useListedCollectionDetails(listedSource?.id, listedSource ? resolved.data?.url : undefined);
    const lastListedUrlRef = useRef<string | undefined>(
        value.type && value.episodeIdentifier ? value.url : undefined,
    );
    useEffect(() => {
        if (!listed.data) return;
        setValue("membershipLevel", DwMembershipLevelReg.Enum.FREE, {shouldValidate: true});
        // Suggest a series, numbered by the Source's own seasons when it has them and by date otherwise.
        if (lastListedUrlRef.current === listed.data.sharingUrl) return;
        lastListedUrlRef.current = listed.data.sharingUrl;
        setValue("type", CollectionTypeReg.Enum.series, {shouldDirty: true});
        setValue(
            "episodeIdentifier",
            listed.data.seasons.length ? EpisodeIdentifierReg.Enum.seasonal : EpisodeIdentifierReg.Enum.date_based,
            {shouldDirty: true},
        );
    }, [listed.data, setValue]);

    // --- Fetch DailyWire data using the slug
    const lastPrefilledUrlRef = useRef<string | undefined>(
        value.type && value.episodeIdentifier ? value.url : undefined,
    );
    const dw: UseQueryResult<any> = useDailywireShow(slugFromUrl);

    // --- Fetch current DailyWire membership level
    const dwUserInfo = useDailywireUserInfo();
    type DwAccessLevelDisplay = typeof DwMembershipLevelReg.values[number] | undefined;
    const dwAccessLevel: DwAccessLevelDisplay = useMemo(() => {
        if (dwUserInfo.isSuccess && dwUserInfo.data) {
            return DwMembershipLevelReg.normalize(dwUserInfo.data.accessLevel) ?? DwMembershipLevelReg.Enum.FREE;
        }
        if (dwUserInfo.isError && dwUserInfo.error?.status === 401) {
            return DwMembershipLevelReg.Enum.FREE;
        }
        if (dwUserInfo.isError) {
            return undefined;
        }
        return DwMembershipLevelReg.Enum.FREE;
    }, [dwUserInfo.isSuccess, dwUserInfo.data, dwUserInfo.isError, dwUserInfo.error]);

    // --- Apply the current membership level to the form
    useEffect(() => {
        if (!slugFromUrl) return;
        setValue('membershipLevel', dwAccessLevel ?? '' as any, {shouldDirty: true});

        if (dwUserInfo.isError) {
            const status = dwUserInfo.error?.status;
            if (status !== 401) {
                setError('membershipLevel', {type: 'server', message: `Failed to fetch current membership level: ${dwUserInfo.error?.detail ?? ''}`});
            }
        }
    }, [dwUserInfo.isError, setValue, setError, dwAccessLevel, slugFromUrl]);

    // --- Prefill defaults for type & episodeIdentifier from the external API when available
    useEffect(() => {
        if (!dw.data) return;
        const currentUrl = watchedUrl ?? "";
        if (currentUrl === (lastPrefilledUrlRef.current ?? "")) return;

        const inferredType: CollectionTypeValue | "" = CollectionTypeReg.normalize(dw.data.probableCollectionType) ?? "";
        const inferredEpisodeId: EpisodeIdentifierValue | "" = inferredType === CollectionTypeReg.Enum.series
            ? EpisodeIdentifierReg.Enum.seasonal
            : (EpisodeIdentifierReg.normalize(dw.data.probableEpisodeIdentification) ?? "");

        setValue("type", inferredType, {shouldDirty: true});
        setValue("episodeIdentifier", inferredEpisodeId, {shouldDirty: true});

        // Remember that we prefetched for this URL to prevent reapplying on mount/reload
        lastPrefilledUrlRef.current = currentUrl;
    }, [dw.data, watchedUrl, setValue]);

    // --- Submit handler
    const onSubmit: SubmitHandler<CollectionCreateFormIn> = (formOnly: CollectionCreateFormIn) => {
        if (!slugFromUrl) {
            if (!listed.data) {
                setError("url", {type: "validate", message: "Paste the link to a collection or channel"});
                return;
            }
            const details = listed.data;
            onSeasonsSubmit(details.seasons);
            onSubmitParent(CollectionCreatePayloadSchema.parse({
                ...formOnly,
                membershipLevel: DwMembershipLevelReg.Enum.FREE,
                sourceKey: details.sourceKey,
                dwId: details.slug,
                slug: details.slug,
                title: details.title,
                description: details.description ?? null,
                backgroundImagePath: null,
                logoImagePath: null,
                sharingUrl: details.sharingUrl,
                authorName: details.authorName,
                authorSlug: details.authorSlug,
                authorHeadshotPath: null,
                thumbnailLandscapePath: details.thumbnailLandscapePath ?? null,
                thumbnailPortraitPath: null,
                thumbnailSquarePath: null,
            }));
            onContinue();
            return;
        }
        // Gather/normalize derived fields from the API response
        const dwShowData = dw.data as DailywireShowRead;

        // Validate dailywire data
        const dailywireParsed: ZodSafeParseResult<DailywireShowRead> = DailywireShowReadSchema.safeParse(dwShowData);

        // Validate seasons
        const seasonsRaw: DailywireSeasonRead[] = dwShowData.seasons;
        const seasonsParsed: ZodSafeParseResult<SeasonDetachedOut[]> = SeasonDetachedSchema.array().safeParse(seasonsRaw);

        if (!dailywireParsed.success) {
            const first = dailywireParsed.error.issues[0];
            setError("url", {
                type: "validate",
                message: "The source returned invalid collection data: " + (first?.message ?? "invalid data")
            });
            throw dailywireParsed.error;
        }

        if (!seasonsParsed.success) {
            const first = seasonsParsed.error.issues[0];
            setError("url", {
                type: "validate",
                message: "The source returned invalid seasons: " + (first?.message ?? "invalid seasons"),
            });
            throw seasonsParsed.error;
        }

        // Validate final payload. We do not save anything yet (only in the final widget step)
        const payload: CollectionCreatePayloadOut = CollectionCreatePayloadSchema.parse({
            ...formOnly,
            ...dailywireParsed.data,
            sourceKey: DAILYWIRE_SOURCE_KEY,
        });
        onSeasonsSubmit(seasonsParsed.data);
        onSubmitParent(payload);
        onContinue();
    }

    const seasonsFromSource = !!listed.data?.seasons.length
    const episodeIdentifierField = (
        <div className="form-row">
            <label htmlFor="episode-identification">Episode identification</label>
            <Controller
                control={control}
                name="episodeIdentifier"
                render={({field}) => (
                    <Select
                        inputId="episode-identification"
                        options={EpisodeIdentifierReg.options}
                        value={EpisodeIdentifierReg.options.find(o => o.value === field.value) ?? null}
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
            <div className="help" id="episode-identification-help">
                <ReadMore summary={<span>How are episodes in this collection identified?</span>}>
                    <p>Determines how collection episodes are grouped in the UI, and how they are indexed.</p>
                    <p><b>Numbered</b> episodes are identified by an episode number. VODLoft will know
                        when an episode is part of another episode (e.g. a clip) and label it as such.</p>
                    <p><b>Date-based</b> episodes are identified simply by their publish date.</p>
                    <p><b>Seasonal</b> episodes are identified by a season number and an episode number, like "S01E01".
                        Auxiliary content like trailers will be identified separately.</p>
                    {listed.data && (seasonsFromSource
                        ? <p>{resolved.data?.source.name} has its own seasons, which VODLoft keeps, and a Seasonal collection keeps its episode numbers too.</p>
                        : <p>{resolved.data?.source.name ?? 'This site'} has no seasons, so VODLoft puts the videos of each upload year in their own season.</p>)}
                    {!listed.data && <p>VODLoft suggests one from the collection itself. If you're unsure, select "Numbered".</p>}
                </ReadMore>
            </div>
        </div>
    )

    // --- Render
    return (
        <form className="form" onSubmit={handleSubmit(onSubmit)} noValidate>
            {errors.root && (
                <div className="form-error-card" role="alert" aria-live="polite">
                    {String(errors.root.message)}
                </div>
            )}
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

            {/* A show from a Source that lists its episodes */}
            {urlParsed.success && !slugFromUrl && (
                <>
                    <div className="form-row" aria-live="polite">
                        {resolved.isPending || listed.isFetching ? (
                            <div className="dw-card" aria-busy="true">
                                <div className="dw-card-body">
                                    <div className="dw-card-title">Checking show…</div>
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
                </>
            )}

            {/* Preview fetched DailyWire show info */}
            {urlParsed.success && slugFromUrl && (
                <>
                    <div className="form-row" aria-live="polite">
                        <DailywireShowCard collectionSlug={slugFromUrl}/>
                    </div>

                    {/* Remaining fields dependent on data from DailyWire */}
                    {dw.isSuccess && !!dw.data && (
                        <>
                            <div className="form-row">
                                <label htmlFor="membership-level">Membership level</label>
                                <Controller
                                    control={control}
                                    name="membershipLevel"
                                    render={({field}) => (
                                        <Select
                                            inputId="membership-level"
                                            options={DwMembershipLevelReg.options}
                                            value={DwMembershipLevelReg.options.find(o => o.value === field.value) ?? null}
                                            onChange={(opt) => field.onChange(opt?.value ?? "")}
                                            onBlur={field.onBlur}
                                            aria-invalid={!!errors.membershipLevel}
                                            aria-describedby={errors.membershipLevel ? 'membership-level-errors' : 'membership-level-help'}
                                            isClearable
                                        />
                                    )}
                                />
                                {errors.membershipLevel && (
                                    <div id="membership-level-errors" className="error" role="alert" aria-live="polite">
                                        {errors.membershipLevel.message as string}
                                    </div>
                                )}
                                <div className="help" id="membership-level-help">
                                    <ReadMore summary={
                                        <span>Current membership level at The Daily Wire: {DwMembershipLevelReg.getLabelLoose(dwAccessLevel ?? 'Unknown')}</span>}>
                                        <p>This sets the membership level used when indexing episodes for this collection.</p>
                                        <p>VODLoft will make sure to only index episodes with at least this membership level.
                                            If your subscription expires, gives access to a lower level membership than configured here, or
                                            VODLoft loses access to your account at The Daily Wire altogether, indexing will be paused.</p>
                                        <p>If you choose <strong>Highest allowed</strong>, VODLoft will index episodes using the membership level
                                            currently available on your connected account at The Daily Wire. However, if this ever changes or
                                            VODLoft loses access to your account, episodes of a different membership level will
                                            be indexed. This might result in a confusing mix of episodes from different membership
                                            levels combined.</p>
                                    </ReadMore>
                                </div>
                            </div>

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
                                    <ReadMore summary={<span>Why do I need to choose this?</span>}>
                                        <p>The collection type defines how download- and stream profiles deal with the collection.</p>
                                        <p><b>Podcast</b> collections download and stream episodes from <i>newest</i> to <i>oldest</i>.</p>
                                        <p><b>Series</b> collections download and stream episodes from <i>oldest</i> to <i>newest</i>.</p>
                                        <p>Further, the collection type also defines what filters are available in the download- and stream profiles.</p>
                                        <p>Though VODLoft tries to guess the collection type automatically based on various factors, Daily&nbsp;Wire
                                            unfortunately does not provide a reliable way to determine this. If you're unsure, select "Podcast".</p>
                                    </ReadMore>
                                </div>
                            </div>

                            {episodeIdentifierField}
                        </>
                    )}
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
