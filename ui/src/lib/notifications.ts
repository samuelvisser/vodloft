import {keepPreviousData, useQuery} from '@tanstack/react-query'

import {
    AppriseServiceReadSchema,
    DeliveryReadSchema,
    DestinationPreviewReadSchema,
    DestinationReadSchema,
    NotificationEventReadSchema,
    PersonalNotificationsReadSchema,
    RuleReadSchema,
    ScriptsReadSchema,
    TestReadSchema,
    WebhookExampleReadSchema,
    type DestinationFormValues,
    type DestinationPreviewRead,
    type RuleFormValues,
    type TestRead,
} from '../types/schemas/notifications'
import {errorMessage} from './users'
import {apiUrl} from './api'

function base(): string {
    return (apiUrl()).replace(/\/+$/, '')
}

async function readJson<T>(path: string, schema: {parse(value: unknown): T}, signal?: AbortSignal): Promise<T> {
    const response = await fetch(`${base()}${path}`, {signal, credentials: 'include'})
    if (!response.ok) throw new Error(await errorMessage(response))
    return schema.parse(await response.json())
}

/** Send a request to the API; the caller decides what a failure means. */
export function notificationsRequest(path: string, method: string, body?: unknown, signal?: AbortSignal): Promise<Response> {
    return fetch(`${base()}${path}`, {
        method,
        signal,
        credentials: 'include',
        headers: body === undefined ? undefined : {'Content-Type': 'application/json'},
        body: body === undefined ? undefined : JSON.stringify(body),
    })
}

async function parsedOrThrow<T>(response: Response, schema: {parse(value: unknown): T}): Promise<T> {
    if (!response.ok) throw new Error(await errorMessage(response))
    return schema.parse(await response.json())
}

export const notificationKeys = {
    events: ['notifications', 'events'] as const,
    services: ['notifications', 'services'] as const,
    destinations: ['notifications', 'destinations'] as const,
    rules: ['notifications', 'rules'] as const,
    history: ['notifications', 'history'] as const,
    scripts: ['notifications', 'scripts'] as const,
    webhookExample: ['notifications', 'webhookExample'] as const,
    personal: ['notifications', 'personal'] as const,
    personalEvents: ['notifications', 'personalEvents'] as const,
}

export function useNotificationEvents(personal = false) {
    return useQuery({
        queryKey: personal ? notificationKeys.personalEvents : notificationKeys.events,
        queryFn: ({signal}) => readJson(personal ? '/account/notifications/events' : '/notifications/events', NotificationEventReadSchema.array(), signal),
        staleTime: Infinity,
    })
}

export function useAppriseServices(enabled: boolean) {
    return useQuery({
        queryKey: notificationKeys.services,
        queryFn: ({signal}) => readJson('/notifications/services', AppriseServiceReadSchema.array(), signal),
        staleTime: Infinity,
        enabled,
    })
}

export function useDestinations() {
    return useQuery({
        queryKey: notificationKeys.destinations,
        queryFn: ({signal}) => readJson('/notifications/destinations', DestinationReadSchema.array(), signal),
        placeholderData: keepPreviousData,
    })
}

export function useRules() {
    return useQuery({
        queryKey: notificationKeys.rules,
        queryFn: ({signal}) => readJson('/notifications/rules', RuleReadSchema.array(), signal),
    })
}

export function useNotificationHistory() {
    return useQuery({
        queryKey: notificationKeys.history,
        queryFn: ({signal}) => readJson('/notifications/history', DeliveryReadSchema.array(), signal),
        refetchInterval: 15_000,
    })
}

export function useScripts(enabled: boolean) {
    return useQuery({
        queryKey: notificationKeys.scripts,
        queryFn: ({signal}) => readJson('/notifications/scripts', ScriptsReadSchema, signal),
        enabled,
    })
}

export function useWebhookExample(enabled: boolean) {
    return useQuery({
        queryKey: notificationKeys.webhookExample,
        queryFn: ({signal}) => readJson('/notifications/webhook-example', WebhookExampleReadSchema, signal),
        enabled,
    })
}

export function usePersonalNotifications() {
    return useQuery({
        queryKey: notificationKeys.personal,
        queryFn: ({signal}) => readJson('/account/notifications', PersonalNotificationsReadSchema, signal),
        refetchInterval: 30_000,
    })
}

/** The settings part of the destination form as the API expects it. */
export function destinationPayload(form: DestinationFormValues) {
    const kind = form.kind ?? 'apprise'
    if (kind === 'apprise') {
        return {
            kind,
            apprise: form.mode === 'url'
                ? {mode: 'url', url: (form.url ?? '').trim()}
                : {mode: 'fields', service: form.service, values: form.values ?? {}},
        }
    }
    if (kind === 'webhook') {
        return {kind, webhook: {url: form.webhookUrl, method: form.method, secretHeader: form.secretHeader, secretValue: form.secretValue}}
    }
    if (kind === 'script') {
        return {kind, script: {script: form.script, timeoutSeconds: Number(form.timeoutSeconds ?? 60)}}
    }
    return {kind, mediaServer: {address: form.address, apiKey: form.apiKey, scope: form.scope, pathFrom: form.pathFrom, pathTo: form.pathTo}}
}

export async function previewDestination(form: DestinationFormValues, signal?: AbortSignal): Promise<DestinationPreviewRead> {
    return parsedOrThrow(
        await notificationsRequest('/notifications/destinations/preview', 'POST', destinationPayload(form), signal),
        DestinationPreviewReadSchema,
    )
}

export async function testUnsavedDestination(form: DestinationFormValues): Promise<TestRead> {
    return parsedOrThrow(
        await notificationsRequest('/notifications/destinations/test', 'POST', {destination: destinationPayload(form)}),
        TestReadSchema,
    )
}

export async function testDestination(destinationId: number): Promise<TestRead> {
    return parsedOrThrow(await notificationsRequest(`/notifications/destinations/${destinationId}/test`, 'POST'), TestReadSchema)
}

export async function changeDestination(destinationId: number, body: {enabled?: boolean}): Promise<void> {
    const response = await notificationsRequest(`/notifications/destinations/${destinationId}`, 'PATCH', body)
    if (!response.ok) throw new Error(await errorMessage(response))
}

export async function deleteDestination(destinationId: number): Promise<void> {
    const response = await notificationsRequest(`/notifications/destinations/${destinationId}`, 'DELETE')
    if (!response.ok) throw new Error(await errorMessage(response))
}

/** Where a rule is saved: Settings, or the person's own page. */
export function rulesPath(personal: boolean): string {
    return personal ? '/account/notifications/rules' : '/notifications/rules'
}

export function rulePayload(values: RuleFormValues) {
    return {...values, collectionIds: values.collectionScope === 'chosen' ? values.collectionIds : []}
}

export async function saveRuleEnabled(personal: boolean, rule: RuleFormValues & {id: number}): Promise<void> {
    const {id, ...values} = rule
    const response = await notificationsRequest(`${rulesPath(personal)}/${id}`, 'PUT', rulePayload(values))
    if (!response.ok) throw new Error(await errorMessage(response))
}

export async function deleteRule(personal: boolean, ruleId: number): Promise<void> {
    const response = await notificationsRequest(`${rulesPath(personal)}/${ruleId}`, 'DELETE')
    if (!response.ok) throw new Error(await errorMessage(response))
}

export async function restoreDefaultRules(): Promise<void> {
    const response = await notificationsRequest('/notifications/rules/restore-defaults', 'POST')
    if (!response.ok) throw new Error(await errorMessage(response))
}

export async function removeDevice(deviceId: number): Promise<void> {
    const response = await notificationsRequest(`/account/notifications/devices/${deviceId}`, 'DELETE')
    if (!response.ok) throw new Error(await errorMessage(response))
}
