# VODLoft's browser extension

Some videos are only there for a signed-in viewer, such as members-only or age-restricted videos. For those, VODLoft
signs in on a site with that site's cookies: the small pieces of data a browser keeps to stay signed in. VODLoft's
browser extension sends them from your browser to VODLoft in one click, so you don't have to export a cookies file.

## Installing it

The extension works in Chrome, Edge, Brave and other Chromium browsers, and in Firefox 128 or later. VODLoft offers it
itself: under **Settings › Sources › Authentication**, open a site, and open **Optional: Send cookies from your browser** under
its cookies file.

1. Choose **Download** and unzip the file.
2. **Chrome, Edge or Brave**: open `chrome://extensions`, turn on **Developer mode**, choose **Load unpacked** and pick
   the unzipped folder.
   **Firefox**: open `about:debugging#/runtime/this-firefox`, choose **Load Temporary Add-on** and pick the
   `manifest.json` file in the folder. Firefox forgets an extension loaded this way when it closes.
3. Pin the VODLoft icon to your toolbar, so it is one click away.

## Setting it up

Click the VODLoft icon and type the address you open VODLoft on, such as `https://vodloft.example.com`. Open the
extension on a VODLoft tab and it fills that address in for you. Choose **Save**, and allow the extension to read the
cookies of sites when your browser asks. It reads a site's cookies only when you choose **Send**, and only sends them
to the address you gave.

Sign in to VODLoft in the same browser: the extension sends the cookies as you, so VODLoft knows you may change them.
Only people who may manage Sources can send cookies.

## Sending a site's cookies

1. Open a page of the site, such as a video, while you are signed in there.
2. Click the VODLoft icon and choose **Send cookies to VODLoft**.

VODLoft finds the site of the page, and the extension sends only the cookies of that site. They replace the site's
cookies file under **Settings › Sources › Authentication**, and VODLoft adds the site there if it did not know it yet.
Sites are signed out after a while: send the cookies again when **Authentication** says a site's cookies stopped
working.

A private window, or a Firefox container, has cookies of its own: the extension sends the cookies of the window or
container you click it in. The Daily Wire signs in with VODLoft itself and takes no cookies.

Treat cookies like a password: they sign VODLoft in as you.
