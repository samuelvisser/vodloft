import {createContext, useContext, useState, type ReactNode} from 'react'

import type {LocalMediaProfilePreview} from '../../types/schemas/local_media_profile_preview'

export type ExampleMetadata = NonNullable<LocalMediaProfilePreview['metadata']>

/** The example episode picked under Output path, and the title and description the profile gives it. */
export type ExampleEpisode = {
    label: string | null
    metadata: ExampleMetadata | null
    loading: boolean
}

const NO_EXAMPLE: ExampleEpisode = {label: null, metadata: null, loading: false}

const ExampleEpisodeContext = createContext<{
    example: ExampleEpisode
    setExample: (example: ExampleEpisode) => void
} | null>(null)

/** Lets the metadata fields show the example episode that the output path's preview renders. */
export function ExampleEpisodeProvider({children}: {children: ReactNode}) {
    const [example, setExample] = useState<ExampleEpisode>(NO_EXAMPLE)
    return <ExampleEpisodeContext.Provider value={{example, setExample}}>{children}</ExampleEpisodeContext.Provider>
}

export function useExampleEpisode(): ExampleEpisode {
    return useContext(ExampleEpisodeContext)?.example ?? NO_EXAMPLE
}

/** Where the output path's preview tells which example it shows; nothing outside a profile form. */
export function useSetExampleEpisode(): ((example: ExampleEpisode) => void) | undefined {
    return useContext(ExampleEpisodeContext)?.setExample
}
