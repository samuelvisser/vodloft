# VODLoft browser extension

Sends the cookies of the site in the current tab to the user's own VODLoft, as that site's cookies file. One folder
serves Chrome (and other Chromium browsers) and Firefox 128 or later, with Manifest V3 and no build step.

- `popup.js` asks VODLoft which site the page is on (`GET /api/sources/authentication/site-of-page`), reads the
  cookies of that site's domains from the tab's cookie store, and sends them as a Netscape cookies file
  (`POST /api/sources/authentication/browser-cookies`). It signs in to VODLoft with the browser's own VODLoft session.
- It asks for access to every site once, when the user saves the VODLoft address, and reads cookies only on Send.

Try it with **Load unpacked** in `chrome://extensions`, or **Load Temporary Add-on** in Firefox's `about:debugging`.
For the stores, zip the folder's contents (`cd browser-extension && zip -r ../vodloft-extension.zip .`). Firefox's store
reviews the same zip under the add-on id in `manifest.json`. Users find the steps in the wiki page Browser-Extension.
