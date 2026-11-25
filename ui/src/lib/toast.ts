import hotToast, {type Renderable, type ToastOptions, type ValueOrFunction, type Toast} from 'react-hot-toast'

type Message = ValueOrFunction<Renderable, Toast>

/** How long react-hot-toast shows each kind of toast when nothing asks for longer. */
const SHORTEST = {blank: 4000, success: 2000, error: 4000} as const

/**
 * Long enough to read a text message at a calm pace, and never shorter than its kind's usual time. A toast that sets
 * its own duration, or shows something other than text, keeps what it asked for.
 */
function withReadingTime(kind: keyof typeof SHORTEST, message: Message, options?: ToastOptions): ToastOptions | undefined {
    if (options?.duration !== undefined || typeof message !== 'string') return options
    const reading = Math.min(15_000, 1000 + message.length * 60)
    return {...options, duration: Math.max(SHORTEST[kind], reading)}
}

/** react-hot-toast's toast, which keeps a long message up until it can be read. Import toasts from here. */
export const toast = Object.assign(
    (message: Message, options?: ToastOptions) => hotToast(message, withReadingTime('blank', message, options)),
    hotToast,
    {
        success: (message: Message, options?: ToastOptions) => hotToast.success(message, withReadingTime('success', message, options)),
        error: (message: Message, options?: ToastOptions) => hotToast.error(message, withReadingTime('error', message, options)),
    },
)

export default toast
