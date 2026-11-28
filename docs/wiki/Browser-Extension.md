# VODLoft's browser extension

VODLoft's browser extension brings VODLoft to the page you are on. Click its icon on a video, a movie or a collection,
such as a YouTube video or channel, and it shows what VODLoft found there, with the same buttons as **Add media**:

- **Add to library** adds a video to your library right away. A movie opens in VODLoft to add it.
- **Add as collection** opens **Add collection** in VODLoft with the page's link, where you choose how to keep it.
- **Quick download** downloads the file without adding it to your library. You choose its quality, format and codec in
  the extension, and it saves the file into your browser's downloads when it is ready. You don't have to open VODLoft.

It can also send the cookies of a site you are signed in to, so VODLoft can download what your account can see there.

## Installing it

The extension works in Chrome, Edge, Brave and other Chromium browsers, and in Firefox 128 or later. VODLoft offers it
itself: on **Add media**, open **Get the browser extension**. It is also under **Settings › Sources › Authentication**,
under a site's cookies file.

1. Choose **Download** and unzip the file.
2. **Chrome, Edge or Brave**: open `chrome://extensions`, turn on **Developer mode**, choose **Load unpacked** and pick
   the unzipped folder.
   **Firefox**: open `about:debugging#/runtime/this-firefox`, choose **Load Temporary Add-on** and pick the
   `manifest.json` file in the folder. Firefox forgets an extension loaded this way when it closes.
3. Pin the VODLoft icon to your toolbar, so it is one click away.

## Setting it up

Click the VODLoft icon and type the address you open VODLoft on, such as `https://vodloft.example.com`. Open the
extension on a VODLoft tab and it fills that address in for you. Choose **Save**, and allow the extension to reach
that address when your browser asks.

The extension and VODLoft are updated apart. When the extension does not work with your VODLoft, it says which of the
two to update: update VODLoft, or download the extension again from VODLoft and load it in place of the old one.

Stay signed in to VODLoft in the same browser: the extension works as you, so it can do what your account may do in
VODLoft, and nothing more. When you are signed out, it says so and links to VODLoft to sign in.

## Quick downloads

Choose **Quick download**, pick a quality or Audio, and **Download**. **Format and codec** has the same choices as the
**Quick download** page, and the rules in **Settings › Quick download** apply here too. Your downloads show in the
extension, with their progress, and the extension saves each file into your browser's downloads as soon as it is
ready. Turn off **Save files to your downloads as soon as they are ready** to save them with a click instead.

**When VODLoft is down**, you can still choose Quick download. The extension keeps the download and sends it to VODLoft
as soon as VODLoft answers again, also after your browser restarted. It does the same when you are signed out, until
you sign in. Without VODLoft to ask, it offers every quality and format; VODLoft takes the closest one the video has.
It goes by what your account could do the last time it reached VODLoft, and VODLoft checks again when it gets the
download: if your account may no longer quick download, the extension shows why the download failed.

VODLoft deletes a ready file after a while, as set in **Settings › Quick download**. Save it before then.

## Sending a site's cookies

Some videos are only there for a signed-in viewer, such as members-only or age-restricted videos. For those, VODLoft
signs in on a site with that site's cookies: the small pieces of data a browser keeps to stay signed in.

1. Open a page of the site, such as a video, while you are signed in there.
2. Click the VODLoft icon, open **Actions** and choose **Send cookies to VODLoft**. The first time, your browser asks you to let the
   extension read sites' cookies. It reads a site's cookies only when you choose Send, and only sends them to VODLoft.

VODLoft finds the site of the page, and the extension sends only the cookies of that site. They replace the site's
cookies file under **Settings › Sources › Authentication**, and VODLoft adds the site there if it did not know it yet.
Sites are signed out after a while: send the cookies again when **Authentication** says a site's cookies stopped
working. Only people who may manage Sources can send cookies.

A private window, or a Firefox container, has cookies of its own: the extension sends the cookies of the window or
container you click it in. The Daily Wire signs in with VODLoft itself and takes no cookies.

Treat cookies like a password: they sign VODLoft in as you.
