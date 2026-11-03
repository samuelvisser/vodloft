import type {DeliveryRead} from '../../types/schemas/notifications'

const STATUS_LABELS: Record<DeliveryRead['status'], string> = {
    PENDING: 'Waiting',
    SENT: 'Sent',
    FAILED: 'Failed',
    CANCELED: 'Not sent',
}

/** What was sent lately, newest first, with the reason when something failed. */
export default function History({deliveries, empty}: {deliveries: DeliveryRead[]; empty: string}) {
    if (deliveries.length === 0) return <p className="notif-empty">{empty}</p>
    return (
        <div className="notif-history-wrap">
            <table className="notif-history">
                <thead>
                    <tr><th>When</th><th>What</th><th>Where</th><th>Result</th></tr>
                </thead>
                <tbody>
                    {deliveries.map((delivery) => (
                        <tr key={delivery.id}>
                            <td>{delivery.at.toLocaleString()}</td>
                            <td>{delivery.title}</td>
                            <td>{delivery.destination}</td>
                            <td>
                                <span className={`notif-delivery notif-delivery--${delivery.status.toLowerCase()}`}>
                                    {STATUS_LABELS[delivery.status]}
                                </span>
                                {delivery.error ? <small>{delivery.error}</small> : null}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
