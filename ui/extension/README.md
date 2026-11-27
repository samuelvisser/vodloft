# VODLoft browser extension

Adds the video, movie or collection of the page in the current tab to the user's own VODLoft, quick downloads it as a
file, and sends a site's cookies to VODLoft. One build serves Chrome (and other Chromium browsers) and Firefox 128 or
later, with Manifest V3.

The extension is made of the UI's own code: its popup is a small React app (`ui/src/extension/popup`) built from the
same components, styles and API functions as Add media and Quick download, and its background script
(`ui/src/extension/background.ts`) uses the same API code. This folder holds what is the extension's alone: its
`popup.html` entry and, in `public/`, its manifest and icons.

- `npm run build:extension` (in `ui/`) builds it into `ui/dist-extension`; `npm run build` builds it with the UI, and
  `npm run dev:extension` rebuilds it on every change. Load `ui/dist-extension` with **Load unpacked** in
  `chrome://extensions`, or as a **Temporary Add-on** in Firefox's `about:debugging`.
- VODLoft offers the built folder as a zip at `GET /api/browser-extension`; the Docker image copies it from the UI build.
- It talks straight to VODLoft's API with the browser's own VODLoft session, after the user allowed it to reach the
  VODLoft address. With that host permission the browser lets it past CORS and sends the session cookie, so VODLoft
  needs no CORS entry and no API token for it.
- Quick downloads wait in the extension's own queue (`queue.ts`) while VODLoft does not answer or the user is signed
  out. The background script hands them to VODLoft once it answers, follows them, and saves each file into the
  browser's downloads when it is ready. An alarm wakes it every half minute while anything is under way.
- Reading cookies takes access to every site, which it asks for only when the user first sends cookies.
