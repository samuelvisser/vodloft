import {useEffect, useMemo, useRef} from "react";
import DailywireShowCard from "./DailywireShowCard";
import ShowPreviewCard from "./ShowPreviewCard";
import {useDailywireShow, useDailywireUserInfo, useListedShowDetails, useResolvedLink} from "../../lib/queries";
import {SourceFeature, sourceHas} from "../../types/schemas/source";
import ReadMore from "../../utils/ReadMore";
import {Controller, SubmitHandler, useForm} from "react-hook-form";
import {zodResolver} from "@hookform/resolvers/zod";
import {ZodSafeParseResult} from "zod";
import {
    ShowCreateFormSchema,
    ShowCreatePayloadSchema,
    type ShowCreateFormIn, ShowCreatePayloadOut, ShowCreatePayloadIn,
} from "../../types/schemas/show";
import {EpisodeIdentifierReg, EpisodeIdentifierValue, ShowTypeReg, ShowTypeValue} from "../../types/show";
import Select from "react-select";
import {UseQueryResult} from "@tanstack/react-query";
import {SeasonDetachedOut, SeasonDetachedSchema} from "../../types/schemas/season";
import {DwMembershipLevelReg} from "../../types/dailywire_user_info";
import {DailywireShowRead, DailywireShowReadSchema} from "../../types/schemas/dailywire_show";
import {DailywireSeasonRead} from "../../types/schemas/dailywire_season";

type Props = {
    value: Partial<ShowCreatePayloadIn>
    onChange: (v: Partial<ShowCreatePayloadIn>) => void;
    onSubmit: (v: ShowCreatePayloadOut) => void;
    onSeasonsSubmit: (seasons: SeasonDetachedOut[]) => void;
    onContinue: () => void;
    onCancel: () => void;
};

export default function ChooseShowStep({value, onChange, onSubmit: onSubmitParent, onSeasonsSubmit, onContinue, onCancel,}: Props) {
    // --- Form: only user-editable fields are in this schema
    const form = useForm<ShowCreateFormIn>({
        resolver: zodResolver(ShowCreateFormSchema),
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
        const subscription = watch((values: ShowCreateFormIn) => {
            onChange(values); // push up on every change
        });
        return () => subscription.unsubscribe();
    }, [watch, onChange]);

    // --- Watch the URL and extract the slug when valid
    const watchedUrl = watch("url");
    const urlParsed = useMemo(() => ShowCreateFormSchema.shape.url.safeParse(watchedUrl ?? ""), [watchedUrl]);
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
    // Sources that list their episodes describe the show themselves.
    const resolved = useResolvedLink(urlParsed.success && !slugFromUrl ? urlParsed.data : undefined);
    const listedSource = resolved.data?.kind === 'show' && sourceHas(resolved.data.source, SourceFeature.EPISODE_LISTS)
        ? resolved.data.source
        : undefined;
    const listed = useListedShowDetails(listedSource?.id, listedSource ? resolved.data?.url : undefined);
    useEffect(() => {
        if (!listed.data) return;
        // Episodes of a listed show are numbered per upload year.
        setValue("episodeIdentifier", EpisodeIdentifierReg.Enum.seasonal, {shouldValidate: true});
        setValue("membershipLevel", DwMembershipLevelReg.Enum.FREE, {shouldValidate: true});
    }, [listed.data, setValue]);

    // --- Watch the type and set the episodeIdentifier to seasonal when the type is series
    const watchedType = watch("type");
    useEffect(() => {
        if (watchedType === ShowTypeReg.Enum.series) {
            setValue("episodeIdentifier", EpisodeIdentifierReg.Enum.seasonal, {shouldValidate: true, shouldDirty: true});
        }
    }, [watchedType, setValue]);

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

        const inferredType: ShowTypeValue | "" = ShowTypeReg.normalize(dw.data.probableShowType) ?? "";
        const inferredEpisodeId: EpisodeIdentifierValue | "" = inferredType === ShowTypeReg.Enum.series
            ? EpisodeIdentifierReg.Enum.seasonal
            : (EpisodeIdentifierReg.normalize(dw.data.probableEpisodeIdentification) ?? "");

        setValue("type", inferredType, {shouldDirty: true});
        setValue("episodeIdentifier", inferredEpisodeId, {shouldDirty: true});

        // Remember that we prefetched for this URL to prevent reapplying on mount/reload
        lastPrefilledUrlRef.current = currentUrl;
    }, [dw.data, watchedUrl, setValue]);

    // --- Submit handler
    const onSubmit: SubmitHandler<ShowCreateFormIn> = (formOnly: ShowCreateFormIn) => {
        if (!slugFromUrl) {
            if (!listed.data) {
                setError("url", {type: "validate", message: "Paste the link to a show or channel"});
                return;
            }
            const details = listed.data;
            onSeasonsSubmit([]);
            onSubmitParent(ShowCreatePayloadSchema.parse({
                ...formOnly,
                membershipLevel: DwMembershipLevelReg.Enum.FREE,
                episodeIdentifier: EpisodeIdentifierReg.Enum.seasonal,
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
                message: "The source returned invalid show data: " + (first?.message ?? "invalid data")
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
        const payload: ShowCreatePayloadOut = ShowCreatePayloadSchema.parse({...formOnly, ...dailywireParsed.data});
        onSeasonsSubmit(seasonsParsed.data);
        onSubmitParent(payload);
        onContinue();
    }

    // --- Render
    return (
        <form className="form" onSubmit={handleSubmit(onSubmit)} noValidate>
            {errors.root && (
                <div className="form-error-card" role="alert" aria-live="polite">
                    {String(errors.root.message)}
                </div>
            )}
            <div className="form-row">
                <label htmlFor="show-url">Show link</label>
                <input
                    id="show-url"
                    className="input"
                    type="url"
                    inputMode="url"
                    placeholder="https://…"
                    {...register("url")}
                    aria-invalid={!!errors.url}
                    aria-describedby={errors.url ? "show-url-validate" : undefined}
                />
                {errors.url && (
                    <div id="show-url-validate" className="error" role="alert" aria-live="polite">
                        {errors.url.message as string}
                    </div>
                )}
                <div id="url-help" className="help">
                    The link to the show's own page, such as a Daily Wire show, a YouTube channel or a playlist.
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
                            <ShowPreviewCard
                                title={listed.data.title}
                                authorName={listed.data.authorName}
                                description={listed.data.description}
                                imageUrl={listed.data.thumbnailLandscapePath}
                            />
                        ) : (
                            <div className="form-error-card" role="alert">
                                {resolved.data?.kind === 'show'
                                    ? `VODLoft cannot add shows from ${resolved.data.source.name} yet.`
                                    : 'This link is not a show. Paste the link to a show, channel or playlist, or add it from Add media.'}
                            </div>
                        )}
                    </div>
                    {listed.data && (
                        <div className="form-row">
                            <label htmlFor="show-type">Show type</label>
                            <Controller
                                control={control}
                                name="type"
                                render={({field}) => (
                                    <Select
                                        inputId="show-type"
                                        options={ShowTypeReg.options}
                                        value={ShowTypeReg.options.find(o => o.value === field.value) ?? null}
                                        onChange={(opt) => field.onChange(opt?.value ?? "")}
                                        onBlur={field.onBlur}
                                        aria-invalid={!!errors.type}
                                        aria-describedby={errors.type ? 'show-type-errors' : 'show-type-help'}
                                        isClearable
                                    />
                                )}
                            />
                            {errors.type && (
                                <div id="show-type-errors" className="error" role="alert" aria-live="polite">
                                    {errors.type.message as string}
                                </div>
                            )}
                            <div className="help" id="show-type-help">
                                <ReadMore summary={<span>Why do I need to choose this?</span>}>
                                    <p><b>Podcast</b> shows download and stream episodes from <i>newest</i> to <i>oldest</i>,
                                        which suits most channels.</p>
                                    <p><b>Series</b> shows download and stream episodes from <i>oldest</i> to <i>newest</i>,
                                        which suits a playlist you watch in order.</p>
                                    <p>Either way, VODLoft puts the videos of each upload year in their own season and numbers
                                        them by upload date, like S2024E01.</p>
                                </ReadMore>
                            </div>
                        </div>
                    )}
                </>
            )}

            {/* Preview fetched DailyWire show info */}
            {urlParsed.success && slugFromUrl && (
                <>
                    <div className="form-row" aria-live="polite">
                        <DailywireShowCard showSlug={slugFromUrl}/>
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
                                        <p>This sets the membership level used when indexing episodes for this show.</p>
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
                                <label htmlFor="show-type">Show type</label>
                                <Controller
                                    control={control}
                                    name="type"
                                    render={({field}) => (
                                        <Select
                                            inputId="show-type"
                                            options={ShowTypeReg.options}
                                            value={ShowTypeReg.options.find(o => o.value === field.value) ?? null}
                                            onChange={(opt) => field.onChange(opt?.value ?? "")}
                                            onBlur={field.onBlur}
                                            aria-invalid={!!errors.type}
                                            aria-describedby={errors.type ? 'show-type-errors' : 'show-type-help'}
                                            isClearable
                                        />

                                    )}
                                />
                                {errors.type && (
                                    <div id="show-type-errors" className="error" role="alert" aria-live="polite">
                                        {errors.type.message as string}
                                    </div>
                                )}
                                <div className="help" id="show-type-help">
                                    <ReadMore summary={<span>Why do I need to choose this?</span>}>
                                        <p>The show type defines how download- and stream profiles deal with the show.</p>
                                        <p><b>Podcast</b> shows download and stream episodes from <i>newest</i> to <i>oldest</i>.</p>
                                        <p><b>Series</b> shows download and stream episodes from <i>oldest</i> to <i>newest</i>.</p>
                                        <p>Further, the show type also defines what filters are available in the download- and stream profiles.</p>
                                        <p>Though VODLoft tries to guess the show type automatically based on various factors, Daily&nbsp;Wire
                                            unfortunately does not provide a reliable way to determine this. If you're unsure, select "Podcast".</p>
                                    </ReadMore>
                                </div>
                            </div>

                            {/* Episode identification selector (only for Podcast) */}
                            {watch("type") === ShowTypeReg.Enum.podcast && (
                                <div className="form-row">
                                    <label htmlFor="episode-identification">Episode identification</label>


                                    <Controller
                                        control={control}
                                        name="episodeIdentifier"
                                        render={({field}) => (
                                            <Select
                                                inputId="show-type"
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
                                        <div id="episode-identification-errors" className="error" role="alert"
                                             aria-live="polite">
                                            {errors.episodeIdentifier.message as string}
                                        </div>
                                    )}
                                    <div className="help" id="episode-identification-help">
                                        <ReadMore summary={<span>How are episodes in this show identified?</span>}>
                                            <p>Determines how show episodes are grouped in the UI, and how they are indexed.</p>
                                            <p><b>Numbered</b> episodes are identified by an episode number. VODLoft will know
                                                when an episode is part of another episode (e.g. a clip) and label it as such.</p>
                                            <p><b>Date-based</b> episodes are identified simply by their publish date.</p>
                                            <p><b>Seasonal</b> episodes are identified by a season number and an episode number. VODLoft will count
                                                episodes by season and identify them like "S01E01". Auxiliary content like trailers will be identified
                                                separately. Episodes in a show of type series are automatically assigned this seasonal identification.
                                                Generally, we do not recommend it for Podcasts.</p>
                                            <p>If you're unsure, select "Numbered".</p>
                                        </ReadMore>
                                    </div>
                                </div>
                            )}
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
