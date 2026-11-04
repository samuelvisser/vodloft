import {useEffect, useState} from 'react'

import type {ExampleCollection} from '../../lib/collectionExamples'
import {RegexCheckSchema, type RegexCheck} from '../../types/schemas/regex'

export type RegexCheckRequest = {
    pattern: string
    ignoreCase: boolean
    samples: string[]
    collectionId: number | null
    /** Or the newest episodes of the collection that is being added. */
    exampleCollection: ExampleCollection | null
    field: 'title' | 'description'
}

export type RegexCheckState = {
    result: RegexCheck | null
    loading: boolean
    error: string
}

/** The server's verdict on a pattern, and what it matches; asked again shortly after each change. */
export function useRegexCheck(request: RegexCheckRequest): RegexCheckState {
    const serialized = JSON.stringify(request)
    const [state, setState] = useState<RegexCheckState>({result: null, loading: true, error: ''})

    useEffect(() => {
        const controller = new AbortController()
        setState((current) => ({...current, loading: true}))
        const timer = window.setTimeout(async () => {
            try {
                const response = await fetch(`${(window as any).appConfig.API_URL}/regex/check`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    signal: controller.signal,
                    body: serialized,
                })
                if (!response.ok) throw new Error(`The server could not test this pattern (${response.status})`)
                const result = RegexCheckSchema.parse(await response.json())
                setState({result, loading: false, error: ''})
            } catch (error) {
                if (controller.signal.aborted) return
                setState({result: null, loading: false, error: error instanceof Error ? error.message : String(error)})
            }
        }, 250)
        return () => {
            controller.abort()
            window.clearTimeout(timer)
        }
    }, [serialized])

    return state
}
