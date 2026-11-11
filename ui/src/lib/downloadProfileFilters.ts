/** The query parameter that filters the Download Profiles table to one Local Media Profile, by id. */
export const LOCAL_MEDIA_PROFILE_QUERY_PARAM = 'localMediaProfile'

/** The Download Profiles table, showing only the profiles that use this Local Media Profile. */
export function downloadProfilesUrlForLocalMediaProfile(localMediaProfileId: number): string {
    return `/download-profiles?${new URLSearchParams({[LOCAL_MEDIA_PROFILE_QUERY_PARAM]: String(localMediaProfileId)})}`
}
