import '../components/Notifications/notifications.css'
import {useCallback} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useQueryClient} from '@tanstack/react-query'
import {Link} from 'react-router-dom'
import toast from 'react-hot-toast'

import PageSubtitle from '../components/common/PageSubtitle'
import History from '../components/Notifications/History'
import Rules from '../components/Notifications/Rules'
import {useBrowserPush} from '../components/Notifications/useBrowserPush'
import {faIcon} from '../icons/faIcon'
import {notificationKeys, removeDevice, useNotificationEvents, usePersonalNotifications} from '../lib/notifications'

/** Account › Notifications: your devices for push, what to push you about, and what was sent to you. */
export default function AccountNotificationsPage() {
    const queryClient = useQueryClient()
    const personal = usePersonalNotifications()
    const events = useNotificationEvents(true)
    const refresh = useCallback(() => {
        void queryClient.invalidateQueries({queryKey: notificationKeys.personal})
    }, [queryClient])
    const push = useBrowserPush(refresh)

    const forget = async (deviceId: number) => {
        try {
            await removeDevice(deviceId)
            refresh()
        } catch (error) {
            toast.error((error as Error).message)
        }
    }

    return (
        <section className="view account-view" aria-labelledby="account-notifications-title">
            <div className="view-header">
                <h1 id="account-notifications-title">Notifications</h1>
                <PageSubtitle summary={<>Push messages to your phone or computer. <Link to="/account">Back to your account</Link></>}/>
            </div>
            <div className="account-notifications">
                <div className="account-card">
                    <h2>This device</h2>
                    {!push.supported ? (
                        <p className="help">
                            This browser cannot get push messages from VODLoft here. Push needs VODLoft over HTTPS; on an
                            iPhone or iPad, first add VODLoft to the home screen from the share menu.
                        </p>
                    ) : push.loading ? <p className="help">Checking…</p> : (
                        <div className="notif-toolbar">
                            {push.enabled ? (
                                <>
                                    <span className="notif-health notif-health--healthy">On for this device</span>
                                    <button type="button" className="btn btn-secondary" disabled={push.busy} onClick={() => void push.test()}>
                                        <FontAwesomeIcon icon={faIcon('fass', 'paper-plane')} aria-hidden="true"/> Send a test
                                    </button>
                                    <button type="button" className="btn btn-secondary" disabled={push.busy} onClick={() => void push.disable()}>
                                        Turn off
                                    </button>
                                </>
                            ) : (
                                <button type="button" className="btn btn-primary" disabled={push.busy} onClick={() => void push.enable()}>
                                    <FontAwesomeIcon icon={faIcon('fass', 'bell')} aria-hidden="true"/> Turn on notifications here
                                </button>
                            )}
                        </div>
                    )}
                    {push.error ? <p className="error" role="alert">{push.error}</p> : null}
                    {personal.data && personal.data.devices.length > 0 ? (
                        <>
                            <h3>Your devices</h3>
                            <ul className="notif-list">
                                {personal.data.devices.map((device) => (
                                    <li key={device.id} className="notif-row notif-row--compact">
                                        <div className="notif-row__main">
                                            <strong>{device.deviceName}</strong>
                                            <p className="notif-row__meta">Since {device.createdAt.toLocaleDateString()}</p>
                                        </div>
                                        <div className="notif-row__actions">
                                            <button type="button" className="btn btn-secondary" onClick={() => void forget(device.id)}>Remove</button>
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        </>
                    ) : null}
                </div>
                <div className="account-card">
                    <h2>What to push me about</h2>
                    {personal.isError ? <p role="alert">Could not load your notifications: {personal.error.message}</p> : null}
                    {personal.data && events.data ? (
                        <Rules rules={personal.data.rules} events={events.data} destinations={[]} personal/>
                    ) : null}
                    <p className="help">You only hear about Collections you can see. Administrators also get the problems set up in Settings › Messages and actions.</p>
                </div>
                <div className="account-card">
                    <h2>Sent to you in the last 30 days</h2>
                    <History deliveries={personal.data?.history ?? []} empty="Nothing was sent to you yet."/>
                </div>
            </div>
        </section>
    )
}
